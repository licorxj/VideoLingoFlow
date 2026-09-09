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
    ) -> None:
        self.base_url = (base_url or resolve_backend_base_url()).rstrip("/")
        self.browser_channel = (browser_channel or "").strip() or None
        self.timeout = max(60.0, float(timeout))
        self.headless = headless

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

                try:
                    context = browser.new_context(viewport={"width": 1920, "height": 1080})
                    context.add_init_script(_INIT_SCRIPT)
                    page = context.new_page()
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

                    self._wait_message(page, "ready", deadline, progress, 5, 15, "正在加载剪辑工作台")

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
                        fail_key="loadFailed",
                    )
                    if state.get("loadFailed"):
                        raise HeadlessRenderError(
                            state["loadFailed"].get("message") or "剪辑项目载入 Cutia 失败"
                        )

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

                    return self._await_export(page, deadline, progress)
                finally:
                    browser.close()

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _post(self, page, message: dict) -> None:
        delivered = page.evaluate(_POST_TO_FRAME_JS, message)
        if not delivered:
            raise HeadlessRenderError("宿主页面未找到剪辑工作台 iframe，无法投递消息。")

    def _read_state(self, page) -> dict:
        return page.evaluate(_READ_STATE_JS) or {}

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
    ) -> dict:
        while time.time() < deadline:
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
    ) -> dict:
        """等待导出完成，期间把 Cutia 的帧进度换算为节点进度。"""
        last_percent = -1
        uploading = False

        while time.time() < deadline:
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

            if progress:
                if state.get("uploading"):
                    if not uploading:
                        uploading = True
                        progress(95, "正在回传剪辑成片")
                elif state.get("started"):
                    raw = (state.get("progress") or {}).get("progress")
                    if isinstance(raw, (int, float)):
                        percent = 30 + int(max(0.0, min(1.0, float(raw))) * 60)
                        if percent != last_percent:
                            last_percent = percent
                            progress(percent, "正在渲染导出成片")

            time.sleep(0.5)

        raise HeadlessRenderError("剪辑渲染导出超时，请尝试降低画质或缩短时间线后重试。")


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
    progress: Optional[Callable[[int, str], None]] = None,
) -> dict:
    """便捷函数：按任务项目执行一次无头渲染。"""
    renderer = CutiaHeadlessRenderer(
        base_url=base_url,
        browser_channel=browser_channel,
        timeout=timeout,
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
