"""无头 Cutia 渲染器。

Cutia 的渲染内核（Canvas 2D 逐帧绘制 + WebCodecs 编码）只能在浏览器上下文运行，
因此本模块用 Playwright 启动无头浏览器，加载一个与后端同源的宿主页面，
在宿主页面内用 iframe 载入 Cutia 编辑器，并通过既有的 ``videolingo:*``
postMessage 协议推送任务项目、触发导出，从而在不打开界面的前提下完成渲染闭环。

协议版本与消息类型必须与以下文件保持一致：
``thirdparty/cutia/apps/web/src/components/videolingo-task-bridge.tsx``
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

# 桥接协议版本，需与 cutia 侧 TASK_PROJECT_BRIDGE_VERSION 一致
BRIDGE_VERSION = 1

# 宿主页面的虚拟路径：由 Playwright 路由拦截返回，保证与后端同源
HOST_PATH = "/videolingo-cutia-render-host"

DEFAULT_BACKEND_PORT = "11001"

# 同一进程内串行化渲染，避免并发拉起过多浏览器实例
_RENDER_LOCK = threading.Lock()

_INIT_SCRIPT = """
window.__vlMessages = [];
window.addEventListener('message', function (event) {
  try { window.__vlMessages.push(event.data || {}); } catch (e) {}
});
"""

_HOST_HTML = """<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>Cutia Render Host</title></head>
<body style="margin:0;background:#000">
<iframe id="cutia-frame" src="{src}" style="width:1920px;height:1080px;border:0"></iframe>
</body>
</html>
"""

_READ_STATE_JS = """
() => {
  const msgs = window.__vlMessages || [];
  const last = (type) => {
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      if (msgs[i] && msgs[i].type === type) return msgs[i];
    }
    return null;
  };
  return {
    ready: last('videolingo:editor-ready'),
    loaded: last('videolingo:load-task-project-complete'),
    loadFailed: last('videolingo:load-task-project-failed'),
    started: last('videolingo:export-started'),
    uploading: last('videolingo:export-uploading'),
    progress: last('videolingo:export-progress'),
    complete: last('videolingo:export-complete'),
    failed: last('videolingo:export-failed'),
    cancelled: last('videolingo:export-cancelled'),
  };
}
"""

_POST_TO_FRAME_JS = """
(message) => {
  const frame = document.getElementById('cutia-frame');
  if (!frame || !frame.contentWindow) return false;
  frame.contentWindow.postMessage(message, window.location.origin);
  return true;
}
"""

# 编码器能力预检：不同 Chromium 内核自带的编解码器不同（chrome-headless-shell
# 通常缺少 H.264/AAC 的专有编码实现）。导出前先探测，避免编码器不可用时
# Output.start() 静默卡住、后端白白等到超时。
_CODEC_PROBE_JS = """
async () => {
  const probe = async (Ctor, config) => {
    if (typeof Ctor === 'undefined') return 'unsupported-api';
    try {
      const r = await Ctor.isConfigSupported(config);
      return r && r.supported ? 'ok' : 'unsupported-codec';
    } catch (e) {
      return 'error:' + ((e && e.message) || String(e));
    }
  };
  const vCfg = (codec) => ({
    codec, width: 1920, height: 1080, bitrate: 6000000, framerate: 30,
  });
  return {
    hasWebCodecs: typeof VideoEncoder !== 'undefined',
    avc: await probe(VideoEncoder, vCfg('avc1.42001f')),
    avcMain: await probe(VideoEncoder, vCfg('avc1.4d0028')),
    vp9: await probe(VideoEncoder, vCfg('vp09.00.10.08')),
    vp8: await probe(VideoEncoder, vCfg('vp8')),
  };
}
"""

# 无进度终止：导出开始后若长时间收不到任何进度变化，判定为卡死并主动失败
DEFAULT_STALL_TIMEOUT = 600.0

_MP4_ADVICE = (
    "当前浏览器内核不支持 H.264 编码，MP4 导出会卡在编码器初始化且永远等不到进度。"
    "请改用 WebM(VP9) 导出；若必须 MP4，可导出 WebM 后用 ffmpeg 转码："
    "ffmpeg -i 成片.webm -c:v libx264 -crf 20 -c:a aac 成片.mp4"
)
_WEBM_ADVICE = "当前浏览器内核不支持 VP9/VP8 编码，请改用 MP4(H.264) 导出或安装完整版 Chromium 内核。"


class HeadlessRenderError(Exception):
    """无头剪辑渲染失败。"""


def resolve_backend_base_url() -> str:
    """解析后端访问地址。

    后端端口由 manager 通过命令行传入（默认 11001），渲染器需要同源访问
    ``/cutia`` 代理，因此优先读取 manager 注入的环境变量。
    """
    port = str(os.environ.get("VIDEOLINGO_BACKEND_PORT") or DEFAULT_BACKEND_PORT).strip()
    host = str(os.environ.get("VIDEOLINGO_BACKEND_HOST") or "127.0.0.1").strip()
    return f"http://{host}:{port}"


def _resolve_stall_timeout(timeout: float, explicit: Optional[float]) -> float:
    """确定「无进度即终止」的阈值（秒）。

    优先级：构造参数 > 环境变量 VIDEOLINGO_RENDER_STALL_TIMEOUT > 默认值。
    默认值取 DEFAULT_STALL_TIMEOUT，但不小于总超时的 10%，避免长任务误判。
    """
    raw = explicit
    if raw is None:
        raw = os.environ.get("VIDEOLINGO_RENDER_STALL_TIMEOUT") or ""
        raw = raw.strip() or None
    try:
        if raw is not None:
            return max(60.0, float(raw))
    except (TypeError, ValueError):
        pass
    return max(120.0, min(DEFAULT_STALL_TIMEOUT, max(60.0, float(timeout)) * 0.25))


def _skip_codec_probe() -> bool:
    """是否跳过导出前的编码器能力预检（误判时可用环境变量关闭）。"""
    flag = (os.environ.get("VIDEOLINGO_RENDER_SKIP_CODEC_PROBE") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def ensure_chromium_installed(progress: Optional[Callable[[int, str], None]] = None) -> None:
    """渲染前确保 Playwright Chromium 内核已安装且与当前 playwright 版本匹配。

    通过 ``playwright install chromium --dry-run`` 解析期望的安装位置，
    检查浏览器可执行文件是否存在；缺失（未安装）或版本号不匹配（目录名
    含版本号，升级 playwright 后目录变化）时自动执行真实下载。
    :raises HeadlessRenderError: 自动下载失败。
    """
    import subprocess
    import sys

    playwright_exe = Path(sys.executable).with_name("playwright.exe")
    if not playwright_exe.is_file():
        playwright_exe = Path(sys.executable).parent / "Scripts" / "playwright.exe"
    cmd_prefix = [str(playwright_exe)] if playwright_exe.is_file() else [sys.executable, "-m", "playwright"]

    def _expected_browser_roots() -> list[Path]:
        """解析 dry-run 输出，返回 chromium / chromium-headless-shell 的安装根目录。"""
        try:
            result = subprocess.run(
                cmd_prefix + ["install", "chromium", "--dry-run"],
                capture_output=True, text=True, timeout=60, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        roots: list[Path] = []
        section_is_chromium = False
        for raw in (result.stdout or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if "playwright" in line:
                # 组件标题行（如 "Chrome Headless Shell ... (playwright chromium-headless-shell v1223)"）
                section_is_chromium = "chromium" in line
            elif section_is_chromium and line.startswith("Install location:"):
                location = line.split(":", 1)[1].strip()
                if location:
                    roots.append(Path(location))
        return roots

    def _has_browser(root: Path) -> bool:
        if not root.is_dir():
            return False
        return any(
            exe.name.lower() in {"chrome.exe", "chrome-headless-shell.exe"}
            for exe in root.rglob("*.exe")
        )

    try:
        roots = _expected_browser_roots()
        if roots and all(_has_browser(root) for root in roots):
            return  # 内核已安装且版本匹配
    except Exception:  # noqa: BLE001 - 探测失败时直接尝试安装
        pass

    if progress:
        progress(2, "Playwright Chromium 内核缺失或版本不匹配，正在自动下载（约 300MB）")
    try:
        result = subprocess.run(cmd_prefix + ["install", "chromium"], timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HeadlessRenderError(f"Playwright Chromium 内核自动下载失败：{exc}") from exc
    if result.returncode != 0:
        raise HeadlessRenderError(
            "Playwright Chromium 内核自动下载失败，请手动执行：playwright install chromium"
        )


class CutiaHeadlessRenderer:
    """驱动无头浏览器完成一次 Cutia 项目导出。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        browser_channel: Optional[str] = None,
        timeout: float = 3600.0,
        headless: bool = True,
        stall_timeout: Optional[float] = None,
    ) -> None:
        self.base_url = (base_url or resolve_backend_base_url()).rstrip("/")
        self.browser_channel = (browser_channel or "").strip() or None
        self.timeout = max(60.0, float(timeout))
        self.headless = headless
        self.stall_timeout = _resolve_stall_timeout(self.timeout, stall_timeout)

    # ------------------------------------------------------------------ #
    # 公开入口
    # ------------------------------------------------------------------ #
    def render(
        self,
        task_id: str,
        project: dict,
        assets: list,
        revision: int,
        export_format: str = "mp4",
        quality: str = "high",
        fps: Optional[int] = None,
        include_audio: bool = True,
        progress: Optional[Callable[[int, str], None]] = None,
    ) -> dict:
        """渲染并导出任务项目，返回后端登记的资源信息。

        :raises HeadlessRenderError: 浏览器不可用、项目加载失败或导出失败。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 依赖缺失提示
            raise HeadlessRenderError(
                "未安装 Playwright，请执行 pip install playwright 后运行 playwright install chromium。"
            ) from exc

        editor_url = f"{self.base_url}/cutia/zh/editor/{task_id}"
        deadline = time.time() + self.timeout

        with _RENDER_LOCK:
            with sync_playwright() as playwright:
                launch_kwargs: dict[str, Any] = {
                    "headless": self.headless,
                    "args": [
                        "--autoplay-policy=no-user-gesture-required",
                        "--disable-dev-shm-usage",
                    ],
                }
                if self.browser_channel:
                    launch_kwargs["channel"] = self.browser_channel

                try:
                    browser = playwright.chromium.launch(**launch_kwargs)
                except Exception as exc:
                    raise HeadlessRenderError(
                        f"无法启动无头浏览器（channel={self.browser_channel or 'chromium'}）：{exc}"
                    ) from exc

                crash_state: dict[str, Any] = {"reason": None}
                try:
                    context = browser.new_context(viewport={"width": 1920, "height": 1080})
                    context.add_init_script(_INIT_SCRIPT)
                    page = context.new_page()

                    def _mark_crash(reason: str):
                        def _handler(*_args):
                            if not crash_state["reason"]:
                                crash_state["reason"] = reason
                        return _handler

                    page.on("crash", _mark_crash("无头浏览器页面崩溃（渲染进程被终止，通常是内存不足或编码器异常）"))
                    context.on("close", _mark_crash("无头浏览器上下文已关闭"))
                    browser.on("disconnected", _mark_crash("无头浏览器已断开连接（进程被杀或崩溃）"))

                    page.route(
                        re.compile(re.escape(HOST_PATH)),
                        lambda route: route.fulfill(
                            status=200,
                            content_type="text/html; charset=utf-8",
                            body=_HOST_HTML.format(src=editor_url),
                        ),
                    )

                    if progress:
                        progress(5, "正在启动无头剪辑渲染器")
                    page.goto(f"{self.base_url}{HOST_PATH}", wait_until="domcontentloaded")

                    self._wait_message(
                        page, "ready", deadline, progress, 5, 15, "正在加载剪辑工作台",
                        crash_state=crash_state,
                    )

                    if progress:
                        progress(15, "正在载入剪辑项目与素材")
                    self._post(
                        page,
                        {
                            "type": "videolingo:load-task-project",
                            "version": BRIDGE_VERSION,
                            "taskId": task_id,
                            "project": project,
                            "assets": assets,
                            "revision": revision,
                        },
                    )
                    state = self._wait_message(
                        page, "loaded", deadline, progress, 15, 30, "正在载入剪辑项目与素材",
                        fail_key="loadFailed", crash_state=crash_state,
                    )
                    if state.get("loadFailed"):
                        raise HeadlessRenderError(
                            state["loadFailed"].get("message") or "剪辑项目载入 Cutia 失败"
                        )

                    if not _skip_codec_probe():
                        if progress:
                            progress(28, "正在检测浏览器编码能力")
                        try:
                            caps = page.evaluate(_CODEC_PROBE_JS) or {}
                        except Exception:  # noqa: BLE001 - 探测失败不阻断导出
                            caps = {}
                        self._ensure_codec_available(caps, export_format)

                    if progress:
                        progress(30, "正在渲染导出成片")
                    self._post(
                        page,
                        {
                            "type": "videolingo:request-export",
                            "version": BRIDGE_VERSION,
                            "taskId": task_id,
                            "format": export_format,
                            "quality": quality,
                            "fps": fps,
                            "includeAudio": include_audio,
                        },
                    )

                    return self._await_export(
                        page, deadline, progress,
                        crash_state=crash_state, stall_timeout=self.stall_timeout,
                    )
                finally:
                    browser.close()

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _post(self, page, message: dict) -> None:
        delivered = page.evaluate(_POST_TO_FRAME_JS, message)
        if not delivered:
            raise HeadlessRenderError("宿主页面未找到剪辑工作台 iframe，无法投递消息。")

    def _raise_if_crashed(self, crash_state: Optional[dict]) -> None:
        """浏览器崩溃/断开时立即失败，不再空等到总超时。"""
        if not crash_state:
            return
        reason = crash_state.get("reason")
        if reason:
            raise HeadlessRenderError(
                f"{reason}。请尝试改用 WebM(VP9) 导出、降低画质或缩短时间线分段渲染。"
            )

    def _read_state(self, page) -> dict:
        try:
            return page.evaluate(_READ_STATE_JS) or {}
        except Exception as exc:  # noqa: BLE001 - 页面崩溃时 Playwright 抛出底层错误
            message = str(exc).lower()
            if "crash" in message or "target closed" in message or "browser has been closed" in message:
                raise HeadlessRenderError(
                    f"无头浏览器页面已崩溃或关闭：{exc}。"
                    "通常是内存不足或编码器初始化失败，建议改用 WebM(VP9) 导出并缩短时间线。"
                ) from exc
            raise

    def _ensure_codec_available(self, caps: dict, export_format: str) -> None:
        """导出前校验目标格式所需编码器是否可用，避免静默卡死。

        探测本身失败（无 WebCodecs API / 页面异常）时不阻断，交由后续流程兜底。
        """
        if not caps or caps.get("hasWebCodecs") is False:
            return
        fmt = str(export_format or "mp4").lower()
        if fmt in {"webm", "webmvp9", "vp9"}:
            needed, label, advice = ("vp9", "vp8"), "VP9/VP8", _WEBM_ADVICE
        else:
            needed, label, advice = ("avc", "avcMain"), "H.264(avc)", _MP4_ADVICE
        if any(caps.get(key) == "ok" for key in needed):
            return
        detail = "，".join(f"{key}={caps.get(key)}" for key in needed)
        raise HeadlessRenderError(
            f"当前无头浏览器内核不支持 {label} 编码（{detail}），无法导出 {fmt.upper()}。"
            f"{advice}（临时跳过该预检可设置环境变量 VIDEOLINGO_RENDER_SKIP_CODEC_PROBE=1）"
        )

    def _wait_message(
        self,
        page,
        key: str,
        deadline: float,
        progress: Optional[Callable[[int, str], None]],
        start_percent: int,
        end_percent: int,
        message: str,
        fail_key: Optional[str] = None,
        crash_state: Optional[dict] = None,
    ) -> dict:
        while time.time() < deadline:
            self._raise_if_crashed(crash_state)
            state = self._read_state(page)
            if state.get(key):
                return state
            if fail_key and state.get(fail_key):
                return state
            time.sleep(0.4)
        raise HeadlessRenderError(f"{message}超时（等待 {key}）。请确认剪辑工作台服务可用。")

    def _await_export(
        self,
        page,
        deadline: float,
        progress: Optional[Callable[[int, str], None]],
        crash_state: Optional[dict] = None,
        stall_timeout: Optional[float] = None,
    ) -> dict:
        """等待导出完成，期间把 Cutia 的帧进度换算为节点进度。

        若导出已开始但长时间收不到任何进度变化，判定为编码器卡死并主动失败，
        避免后端一直空等到总超时。
        """
        stall = max(60.0, float(stall_timeout or DEFAULT_STALL_TIMEOUT))
        last_percent = -1
        uploading = False
        started = False
        last_activity = time.time()

        while time.time() < deadline:
            self._raise_if_crashed(crash_state)
            state = self._read_state(page)

            failed = state.get("failed")
            if failed:
                raise HeadlessRenderError(failed.get("message") or "剪辑渲染导出失败")

            if state.get("cancelled"):
                raise HeadlessRenderError("剪辑渲染已取消")

            if state.get("complete"):
                if progress:
                    progress(100, "剪辑成片已导出")
                return state["complete"]

            active = False
            if state.get("started") and not started:
                started = True
                active = True
            if state.get("uploading"):
                # 回传成片阶段无细粒度进度，持续刷新活跃时间，交由总超时兜底
                if not uploading:
                    uploading = True
                    if progress:
                        progress(95, "正在回传剪辑成片")
                active = True
            elif state.get("started"):
                raw = (state.get("progress") or {}).get("progress")
                if isinstance(raw, (int, float)):
                    percent = 30 + int(max(0.0, min(1.0, float(raw))) * 60)
                    if percent != last_percent:
                        last_percent = percent
                        active = True
                        if progress:
                            progress(percent, "正在渲染导出成片")

            if active:
                last_activity = time.time()
            elif time.time() - last_activity > stall:
                raise HeadlessRenderError(self._stall_message(started, last_percent, stall))

            time.sleep(0.5)

        raise HeadlessRenderError("剪辑渲染导出超时，请尝试降低画质或缩短时间线后重试。")

    @staticmethod
    def _stall_message(started: bool, last_percent: int, stall: float) -> str:
        minutes = max(1, int(stall // 60))
        if not started:
            return (
                f"剪辑渲染已触发但连续 {minutes} 分钟未收到任何导出进度，已主动终止。"
                "最常见原因是所选格式的编码器在当前浏览器内核不可用（如 H.264/MP4），"
                "请改用 WebM(VP9) 导出；若必须 MP4，可导出 WebM 后用 ffmpeg 转码。"
            )
        at = last_percent if last_percent > 0 else 30
        return (
            f"剪辑渲染已开始但连续 {minutes} 分钟进度无变化（卡在约 {at}%），已主动终止。"
            "建议：改用 WebM(VP9)、降低画质/分辨率，或缩短时间线分段渲染后重试。"
            "（如需放宽该阈值，设置环境变量 VIDEOLINGO_RENDER_STALL_TIMEOUT=<秒>）"
        )


def render_project(
    task_id: str,
    project: dict,
    assets: list,
    revision: int,
    export_format: str = "mp4",
    quality: str = "high",
    fps: Optional[int] = None,
    include_audio: bool = True,
    base_url: Optional[str] = None,
    browser_channel: Optional[str] = None,
    timeout: float = 3600.0,
    stall_timeout: Optional[float] = None,
    progress: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """便捷函数：按任务项目执行一次无头渲染。"""
    renderer = CutiaHeadlessRenderer(
        base_url=base_url,
        browser_channel=browser_channel,
        timeout=timeout,
        stall_timeout=stall_timeout,
    )
    return renderer.render(
        task_id=task_id,
        project=project,
        assets=assets,
        revision=revision,
        export_format=export_format,
        quality=quality,
        fps=fps,
        include_audio=include_audio,
        progress=progress,
    )


__all__ = [
    "BRIDGE_VERSION",
    "CutiaHeadlessRenderer",
    "HeadlessRenderError",
    "render_project",
    "resolve_backend_base_url",
]
