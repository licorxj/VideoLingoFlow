"""即梦（Jimeng / dreamina）CLI 调用服务。

从 Infinite-Canvas 的即梦调用逻辑迁移：通过本地子进程调用 dreamina CLI 实现文生图 / 图生图 / 文生视频 / 图生视频。
需要本机已安装并登录即梦 CLI（curl -fsSL https://jimeng.jianying.com/cli | bash && dreamina login）。

配置（来自 settings.aigc.jimeng）：
- bin: ""   可执行文件路径（留空自动探测 dreamina / dreamina.exe）
- use_wsl: false  在非 WSL 的 Windows 上通过 wsl.exe 调用
- timeout: 120 单次 CLI 调用超时（秒）

说明：即梦 CLI 的具体子命令与参数随版本变化，本服务封装进程调用与 JSON 结果提取，
实际命令拼装由调用方（节点步骤）根据版本构造，保持与 IC 一致的可扩展结构。
"""
import os
import re
import json
import shlex
import platform
import asyncio
import shutil
import subprocess

from backend.aigc.errors import AIGCError


def jimeng_cli_executable(config: dict) -> str:
    use_wsl = str(config.get("use_wsl") or "").strip().lower() in {"1", "true", "yes", "on", "wsl"}
    if use_wsl:
        return shutil.which("wsl.exe") or shutil.which("wsl") or "wsl.exe"
    configured = str(config.get("bin") or "").strip()
    if configured:
        return configured
    return shutil.which("dreamina") or shutil.which("dreamina.exe") or shutil.which("dreamina.cmd") or ""


def jimeng_use_wsl(config: dict) -> bool:
    return str(config.get("use_wsl") or "").strip().lower() in {"1", "true", "yes", "on", "wsl"}


def _decode_cli_output(stdout: bytes, stderr: bytes, use_wsl: bool) -> tuple:
    out_text = stdout.decode("utf-8", errors="replace").strip()
    err_text = stderr.decode("utf-8", errors="replace").strip()
    return out_text, err_text


def _extract_json(text: str):
    """从 CLI 混合输出中提取最可能的 JSON 对象。"""
    if not text:
        return None
    # 优先提取 ```json ``` 围栏
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    # 提取最后一个 { ... } 对象
    candidates = []
    for m in re.finditer(r"\{.*\}", text, re.DOTALL):
        snippet = m.group(0)
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict):
                candidates.append((len(snippet), obj))
        except Exception:
            pass
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[-1][1]
    return None


def _has_result_payload(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    keys = {str(k).lower() for k in obj.keys()}
    return any(k in keys for k in ("submit_id", "gen_status", "result_json", "images", "videos", "data", "total_credit"))


class JimengService:
    """即梦 CLI 调用。"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.timeout = int(self.config.get("timeout") or 120)

    def _command(self, args: list) -> list:
        exe = jimeng_cli_executable(self.config)
        if not exe:
            raise AIGCError("未找到 dreamina CLI。请先安装：curl -fsSL https://jimeng.jianying.com/cli | bash，并完成 dreamina login。")
        clean_args = [str(a) for a in args if str(a) != ""]
        if jimeng_use_wsl(self.config):
            shell_line = (
                "DREAMINA_BIN=$(command -v dreamina || find \"$HOME\" -maxdepth 4 -type f -name dreamina 2>/dev/null | head -n 1); "
                "if [ -z \"$DREAMINA_BIN\" ]; then echo 'dreamina CLI not found in WSL' >&2; exit 127; fi; "
                "\"$DREAMINA_BIN\" " + " ".join(shlex.quote(a) for a in clean_args)
            )
            return [exe, "-e", "sh", "-lc", shell_line]
        return [exe, *clean_args]

    def run_cli(self, args: list, raw_text: bool = False) -> dict:
        """同步运行即梦 CLI 子进程，返回解析后的 JSON（或含 _stdout/_stderr 的字典）。"""
        return asyncio.run(self.run_cli_async(args, raw_text=raw_text))

    async def run_cli_async(self, args: list, raw_text: bool = False) -> dict:
        command = self._command(args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError as e:
            raise AIGCError(f"即梦 CLI 执行超时：{' '.join(command[:3])}") from e
        except FileNotFoundError as e:
            raise AIGCError(f"未找到即梦 CLI：{command[0]}") from e

        out_text, err_text = _decode_cli_output(stdout, stderr, jimeng_use_wsl(self.config))
        if proc.returncode != 0:
            if out_text:
                raw = _extract_json(out_text)
                if isinstance(raw, dict) and _has_result_payload(raw):
                    raw.setdefault("_stdout", out_text)
                    if err_text:
                        raw.setdefault("_stderr", err_text)
                    return raw
            message = err_text or out_text or f"exit={proc.returncode}"
            raise AIGCError(f"即梦 CLI 调用失败：{message[:1000]}")
        if raw_text:
            return {"_stdout": out_text, "_stderr": err_text}
        raw = _extract_json(f"{out_text}\n{err_text}".strip())
        if isinstance(raw, dict):
            raw.setdefault("_stdout", out_text)
            if err_text:
                raw.setdefault("_stderr", err_text)
        return raw or {"_stdout": out_text, "_stderr": err_text}

    def version(self) -> str:
        for flag in ("--version", "-V", "version"):
            try:
                raw = self.run_cli([flag], raw_text=True)
            except AIGCError:
                continue
            text = raw.get("_stdout") or raw.get("_stderr") or ""
            m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
            if m:
                return m.group(0)
        return ""

    def install_cli(self) -> dict:
        """检查即梦 CLI 是否已安装；未安装时按平台执行官方安装命令并验证。

        - Windows：优先通过 WSL 执行安装（bash 安装脚本），否则回退本机 bash（如 Git Bash）
        - macOS / Linux：直接 bash 执行
        安装命令：curl -s https://jimeng.jianying.com/cli | bash
        """
        exe = jimeng_cli_executable(self.config)
        if exe:
            return {"installed": True, "message": f"已检测到即梦 CLI：{exe}", "exe": exe}

        install_url = "https://jimeng.jianying.com/cli"
        script_line = f"curl -s {install_url} | bash"
        sys_name = platform.system().lower()
        if sys_name == "windows":
            wsl = shutil.which("wsl.exe") or shutil.which("wsl")
            bash = shutil.which("bash")
            if wsl:
                cmd = [wsl, "bash", "-lc", script_line]
                via = "WSL"
            elif bash:
                cmd = [bash, "-lc", script_line]
                via = "bash"
            else:
                raise AIGCError(
                    "Windows 下未找到 WSL 或 bash，无法自动安装即梦 CLI。"
                    "请先安装 WSL（https://learn.microsoft.com/windows/wsl/install）后重试，"
                    "或参照 https://jimeng.jianying.com/cli 手动安装。"
                )
        else:
            bash = shutil.which("bash") or "/bin/bash"
            cmd = [bash, "-lc", script_line]
            via = "bash"

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired as e:
            raise AIGCError("安装即梦 CLI 超时，请检查网络后重试") from e
        except FileNotFoundError as e:
            raise AIGCError(f"未找到执行器 {cmd[0]}，无法安装即梦 CLI") from e

        tail = (proc.stdout or "").strip().splitlines()
        tail = tail[-1] if tail else ""
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise AIGCError(f"安装即梦 CLI 失败（{via}）：{detail or f'exit={proc.returncode}'}")

        # 安装成功后重新探测（WSL 场景下 CLI 位于 WSL 内，Windows 侧可能探测不到，仅提示）
        exe = jimeng_cli_executable(self.config)
        message = f"即梦 CLI 安装完成（{via}）" + (f"，CLI：{exe}" if exe else "，请确认 WSL 环境内已登录（dreamina login）")
        if tail:
            message += f"：{tail}"
        return {"installed": True, "message": message, "exe": exe}

    # ── 高层封装：文生图 / 图生图 / 文生视频 / 图生视频 ───────────────
    # 命令结构与 IC 保持一致：text2image / image2image / text2video /
    # image2video / frames2video / multiframe2video。

    IMAGE_TEXT_MODELS = {"3.0", "3.1", "4.0", "4.1", "4.5", "4.6", "4.7", "5.0", "5.0pro"}
    IMAGE_IMG_MODELS = {"4.0", "4.1", "4.5", "4.6", "4.7", "5.0", "5.0pro"}
    VIDEO_MODELS = {
        "seedance1.0fast", "seedance1.5pro", "seedance2.0", "seedance2.0fast",
        "seedance2.0_vip", "seedance2.0fast_vip", "seedance2.0mini",
    }

    @staticmethod
    def _normalize_image_model(model: str) -> str:
        text = str(model or "").strip()
        if re.search(r"\b5(?:\.0)?\s*[-_ ]?pro\b", text, re.IGNORECASE):
            return "5.0pro"
        m = re.search(r"(\d+\.\d+)", text)
        return m.group(1) if m else ""

    @staticmethod
    def _video_resolution_text(value: str) -> str:
        requested = str(value or "").strip().lower()
        if requested in ("4k", "4kp"):
            return "4k"
        if requested in ("1080p", "1080"):
            return "1080p"
        if requested in ("720p", "720"):
            return "720p"
        return "720p"

    def _poll_seconds(self, duration: float | int = 0) -> str:
        """查询轮询间隔（秒）。

        有视频时长时按 max(10, duration/10) 计算；其余场景回退到配置 poll（默认 60）。
        """
        d = int(duration or 0)
        if d > 0:
            return str(max(10, int(d / 10)))
        return str(int(self.config.get("poll") or 60))

    def generate_image(
        self,
        prompt: str,
        images: list | None = None,
        model: str = "",
        resolution: str = "",
        ratio: str = "",
        num_images: int = 1,
        callback=None,
    ) -> dict:
        """文生图 / 图生图。

        images: 本地图片绝对路径列表（图生图时使用，空则文生图）。
        model: 模型名（如 4.5 / 5.0Pro）。
        resolution: 分辨率文本（1k/2k/4k 或 1920x1080），用于推导 --resolution_type。
        ratio: 比例（如 16:9），仅文生图使用。
        num_images: 生成数量，逐张调用 CLI。
        """
        images = [p for p in (images or []) if p and os.path.isfile(p)]
        sub_cmd = "image2image" if images else "text2image"
        base = [f"--resolution_type={self._image_resolution_type_from_text(resolution)}"]
        if images:
            base.append(f"--images={','.join(images)}")
        elif ratio:
            base.append(f"--ratio={ratio}")
        if model:
            mv = self._normalize_image_model(model)
            allowed = self.IMAGE_IMG_MODELS if images else self.IMAGE_TEXT_MODELS
            if mv in allowed:
                base.append(f"--model_version={mv}")
        base.append(f"--poll={self._poll_seconds()}")

        result = None
        for i in range(max(1, int(num_images or 1))):
            args = [sub_cmd, *base, f"--prompt={prompt}"]
            result = self.run_cli(args)
            if callback:
                callback(40 + (i + 1) * 50 // max(1, int(num_images or 1)), f"即梦生图第 {i + 1}/{num_images} 张")
        return result or {}

    def _image_resolution_type_from_text(self, resolution: str) -> str:
        """由分辨率文本（1920x1080 / 1k / 2k / 4k / 1080p）推导 --resolution_type。"""
        text = str(resolution or "").strip().lower().replace("×", "x")
        m = re.fullmatch(r"(\d+)k", text)
        if m:
            return {"1": "1k", "2": "2k", "3": "2k", "4": "4k"}.get(m.group(1), "2k")
        m = re.fullmatch(r"(\d+)\s*x\s*(\d+)", text)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            if max(w, h) > 3072:
                return "4k"
            if max(w, h) > 1536:
                return "2k"
            return "1k"
        m = re.fullmatch(r"(\d+)p", text)
        if m:
            return "4k" if int(m.group(1)) >= 2160 else ("2k" if int(m.group(1)) >= 1080 else "1k")
        return "2k"

    def generate_video(
        self,
        prompt: str,
        images: list | None = None,
        ref_video: str = "",
        model: str = "",
        resolution: str = "",
        ratio: str = "",
        duration: int = 5,
        callback=None,
    ) -> dict:
        """文生视频 / 图生视频 / 首尾帧视频 / 多帧视频 / 参考视频(全能参考)。

        images: 按顺序 [首帧, 图片2, 图片3, 图片4, 尾帧] 过滤空后的本地路径。
          - 0 张：text2video
          - 1 张：image2video
          - ≥2 张且首尾均有：frames2video（--first/--last）
          - 其余：multiframe2video（--images）
        ref_video: 本地参考视频路径；提供时走 multimodal2video（可同时带图片）。
        """
        images = [p for p in (images or []) if p and os.path.isfile(p)]
        first = images[0] if images else ""
        last = images[-1] if len(images) >= 2 else ""
        has_first_last = bool(first and last and len(images) == 2)

        if ref_video and os.path.isfile(ref_video):
            # 全能参考：图片 + 视频 混合输入
            sub_cmd, args = "multimodal2video", [
                f"--prompt={prompt}",
                f"--duration={max(4, min(15, int(duration or 5)))}",
            ]
            if ratio:
                args.append(f"--ratio={ratio}")
            args.append(f"--video_resolution={self._video_resolution_text(resolution)}")
            for img in images[:9]:
                args.append(f"--image={img}")
            args.append(f"--video={ref_video}")
        elif len(images) == 0:
            sub_cmd, args = "text2video", [
                f"--prompt={prompt}",
                f"--duration={max(4, min(15, int(duration or 5)))}",
            ]
            if ratio:
                args.append(f"--ratio={ratio}")
            args.append(f"--video_resolution={self._video_resolution_text(resolution)}")
        elif has_first_last:
            sub_cmd, args = "frames2video", [
                f"--first={first}",
                f"--last={last}",
                f"--prompt={prompt}",
                f"--duration={max(4, min(15, int(duration or 5)))}",
                f"--video_resolution={self._video_resolution_text(resolution)}",
            ]
        elif len(images) == 1:
            sub_cmd, args = "image2video", [
                f"--image={first}",
                f"--prompt={prompt}",
                f"--duration={max(4, min(15, int(duration or 5)))}",
                f"--video_resolution={self._video_resolution_text(resolution)}",
            ]
        else:
            sub_cmd, args = "multiframe2video", [
                f"--images={','.join(images)}",
                f"--video_resolution={self._video_resolution_text(resolution)}",
            ]

        if model:
            version = str(model).strip().lower()
            if version in self.VIDEO_MODELS:
                args.append(f"--model_version={version}")
        args.append(f"--poll={self._poll_seconds(duration)}")
        if callback:
            callback(30, f"调用即梦 CLI：{sub_cmd}")
        return self.run_cli([sub_cmd, *args])

    def query_task(self, submit_id: str) -> dict:
        """查询已提交任务的进度与结果。"""
        return self.run_cli(["task", "query", "--id", submit_id])
