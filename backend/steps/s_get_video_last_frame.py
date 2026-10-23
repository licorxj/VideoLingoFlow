"""s_get_video_last_frame: 获取视频的尾帧图片。

复用「视频抽帧」(``s_video_frame_extract``) 的 ffmpeg 取帧写法，但定位点固定为视频尾部：
默认取最末一帧，可通过 ``frame_offset`` 设置「从尾部偏移 N 秒」后取该位置之前的最末帧
（例如偏移 1.0 即跳过片尾 1 秒 logo，取其前一帧）。
"""
import json
import os
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".ts", ".m2ts", ".wmv")


def _get_video_duration(video_path: str) -> float:
    """用 ffprobe 读取视频时长（秒），带纯文本回退。"""
    def _run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            raise RuntimeError("ffprobe not found. Please install ffmpeg.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffprobe timed out after 60 seconds")

    result = _run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path])
    stdout = result.stdout
    if result.returncode == 0 and stdout and stdout.strip():
        try:
            info = json.loads(stdout)
            duration = info.get("format", {}).get("duration")
            if duration is not None:
                return float(duration)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    fallback = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ])
    text = (fallback.stdout or "").strip()
    if fallback.returncode == 0 and text:
        try:
            return float(text)
        except ValueError:
            pass

    stderr = (result.stderr or fallback.stderr or "").strip()
    detail = stderr or (stdout or "").strip() or "ffprobe 无输出"
    raise RuntimeError(f"无法获取视频时长: {detail[:300]}")


def _get_fps(video_path: str) -> float:
    """读取视频平均帧率（fps），读取失败返回 0。"""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate",
            "-of", "default=nokey=1:noprint_wrappers=1",
            video_path,
        ], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            value = (result.stdout or "").strip()
            if value and "/" in value:
                num, den = value.split("/")
                den_f = float(den)
                if den_f:
                    return float(num) / den_f
    except Exception:
        pass
    return 0.0


def _get_frame_count(video_path: str) -> int:
    """用 ffprobe 精确统计帧数（全量解码），失败返回 0。"""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-count_frames", "-show_entries", "stream=nb_read_frames",
            "-of", "default=nokey=1:noprint_wrappers=1",
            video_path,
        ], capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            value = (result.stdout or "").strip()
            if value.isdigit():
                n = int(value)
                if n > 0:
                    return n
    except Exception:
        pass
    return 0


def _run_ss_extract(video_path: str, seek: float, nframes: int, output_path: str) -> bool:
    """输入定位（-ss）后提取 nframes 帧；多次覆盖写同一文件，最终落盘为命中的最后一帧。"""
    from backend.utils.ffmpeg_guard import apply_resource_args
    cmd = apply_resource_args([
        "ffmpeg", "-y",
        "-ss", f"{seek:.3f}",
        "-i", video_path,
        "-frames:v", str(nframes),
        "-q:v", "2",
        output_path,
    ])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
    return result.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 0


def _run_select_extract(video_path: str, index: int, output_path: str) -> bool:
    """按帧序号精确提取（全量解码，保证命中目标帧）。"""
    from backend.utils.ffmpeg_guard import apply_resource_args
    cmd = apply_resource_args([
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"select=eq(n\\,{index})",
        "-frames:v", "1",
        "-q:v", "2",
        "-vsync", "vfr",
        output_path,
    ])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
    return result.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 0


def _extract_last_frame(video_path: str, output_path: str, tail: float, duration: float,
                        cancel_callback: Optional[Callable] = None) -> bool:
    """提取 tail 秒之前的最末帧。无偏移时单帧定位（快），有偏移时按帧号精确提取。"""
    fps = _get_fps(video_path)
    if cancel_callback is not None:
        cancel_callback()

    # 快速路径：取最末帧（无偏移）时，直接定位到「末帧时刻」做单帧提取，无需全量解码
    if fps > 0 and duration > 0 and abs(tail - duration) < 1e-6:
        frame_dur = 1.0 / fps
        seek = max(0.0, duration - frame_dur)
        if _run_ss_extract(video_path, seek, 1, output_path):
            return True

    # 精确路径：按帧号提取（支持从尾部偏移，tail 内的最末帧序号 = floor(tail*fps)）
    n = _get_frame_count(video_path)
    if n > 0:
        if cancel_callback is not None:
            cancel_callback()
        index = int(tail * fps) if fps > 0 else (n - 1)
        index = max(0, min(index, n - 1))
        if _run_select_extract(video_path, index, output_path):
            return True

    # 兜底：尾部附近单帧（帧率/帧数均未知等极端情况）
    if tail > 0:
        return _run_ss_extract(video_path, max(0.0, tail - 0.1), 1, output_path)
    return False


def _resolve_video(task_dir: str, step_inputs: dict):
    """解析视频路径：严格优先连线输入的视频，绝不拿 cache 里的输入视频顶替。

    返回 ``(path, invalid_raw)``：
      - path 为找到的视频绝对路径（空串代表未找到）；
      - invalid_raw 为「视频端口已连线但文件无效/不存在」时的原始值（用于严格报错）。
    兼容上游输出端口名与本节点不一致的情况（如「视频加载器/文件加载」输出 ``filepath``）。
    仅当完全未连接任何视频时，才回退扫描 cache 中的输入视频。
    """
    # 1) 严格优先：本节点 video 端口（被连线赋值）
    raw = step_inputs.get("video", "")
    if raw:
        p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
        if os.path.isfile(p):
            return p, None
        # 已连到 video 端口但文件无效 -> 严格标记，不回退
        return "", raw

    # 2) 兼容其它输入端口（上游输出名不是 video，例如 filepath）
    skip_keys = {"srt", "json", "subtitle", "subtitle_path", "patch_json", "text"}
    for key, val in step_inputs.items():
        if key in skip_keys or key == "video":
            continue
        for c in (val if isinstance(val, (list, tuple)) else [val]):
            text = str(c or "").strip()
            if not text.lower().endswith(_VIDEO_EXTS):
                continue
            p = text if os.path.isabs(text) else os.path.join(task_dir, text)
            if os.path.isfile(p):
                return p, None

    # 3) 完全没有连线视频时，回退 cache 中的输入视频（工作流程主输入）
    cache_dir = os.path.join(task_dir, "cache")
    if os.path.isdir(cache_dir):
        for f in sorted(os.listdir(cache_dir)):
            if f.startswith("input_video") and f.lower().endswith(_VIDEO_EXTS):
                return os.path.join(cache_dir, f), None
        for f in sorted(os.listdir(cache_dir)):
            if f.lower().endswith(_VIDEO_EXTS):
                return os.path.join(cache_dir, f), None
    return "", None


class S_GetVideoLastFrame(BaseStep):
    step_id = "s_get_video_last_frame"
    step_name = "获取视频尾帧"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        path = os.path.join(task_dir, "cache", f"last_frame_{node_id}.png")
        return os.path.isfile(path)

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        video_path, invalid = _resolve_video(task_dir, step_inputs)
        if invalid:
            return False
        return bool(video_path)

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        video_path, invalid = _resolve_video(task_dir, step_inputs)
        if invalid:
            raise FileNotFoundError(
                f"视频端口已连接，但文件路径无效或不存在：{invalid}（请确认上游节点已成功产出视频）。"
            )
        if not video_path:
            raise FileNotFoundError("未连接视频输入或缓存中未找到视频文件。")

        if callback:
            callback(10, f"视频: {os.path.basename(video_path)}")

        duration = _get_video_duration(video_path)
        if duration <= 0:
            raise ValueError("无法获取视频时长。")

        # 从尾部偏移（秒）；0 = 取最末帧
        try:
            offset = max(0.0, float(node_config.get("frame_offset", 0) or 0))
        except (TypeError, ValueError):
            offset = 0.0
        tail = max(0.0, duration - offset)
        if callback:
            callback(30, f"视频时长 {duration:.2f}s，尾帧定位点 {tail:.2f}s")

        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        output_path = os.path.join(cache_dir, f"last_frame_{node_id}.png")

        if callback:
            callback(60, "提取尾帧...")
        if not _extract_last_frame(video_path, output_path, tail, duration, cancel_callback):
            raise RuntimeError("ffmpeg 提取尾帧失败。")

        if cancel_callback is not None:
            cancel_callback()

        if callback:
            callback(100, f"完成: last_frame_{node_id}.png")

        return {
            "artifacts": [f"cache/last_frame_{node_id}.png"],
            "outputs": {
                "image": f"cache/last_frame_{node_id}.png",
                "text": f"尾帧 @ {tail:.2f}s (视频时长 {duration:.2f}s)",
            },
        }
