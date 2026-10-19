"""s_get_video_info: 获取视频信息（帧率 / 时长 / 宽度 / 高度）。

纯探测节点，**不落盘**：四个端口全部以文本形式输出数值。

读取策略（按用户要求）：
1. 优先用 ffprobe（ffmpeg）一次请求同时读取流与容器信息；
2. ffprobe 失败或任一指标缺失时，回退 OpenCV（cv2.VideoCapture）；
3. 两者都失败时抛出带详细原因的 RuntimeError。
"""
import json
import os
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".ts",
               ".m2ts", ".wmv", ".m4v", ".mpg", ".mpeg", ".rmvb", ".3gp")


def _fmt_number(value: float) -> str:
    """把浮点数格式化为紧凑文本：30.000000 -> 30，29.970000 -> 29.97。"""
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


def _parse_frame_rate(value) -> float:
    """解析 ffprobe 的帧率字段（形如 `30000/1001` 的有理数或普通数字）。"""
    try:
        text = str(value if value is not None else "").strip()
        if not text:
            return 0.0
        if "/" in text:
            num, den = text.split("/", 1)
            den_f = float(den)
            if not den_f:
                return 0.0
            return float(num) / den_f
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _complete(info) -> bool:
    """四项指标是否齐全且有效。"""
    return bool(
        info
        and info.get("fps", 0) > 0
        and info.get("duration", 0) > 0
        and info.get("width", 0) > 0
        and info.get("height", 0) > 0
    )


def _probe_with_ffmpeg(video_path: str) -> tuple:
    """用 ffprobe 读取视频信息，返回 (info|None, 失败原因)。"""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", video_path,
        ], capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None, "未找到 ffprobe（请确认已安装 ffmpeg）"
    except subprocess.TimeoutExpired:
        return None, "ffprobe 超时（60s）"
    except Exception as exc:  # 兜底，避免异常裸抛
        return None, f"ffprobe 执行异常: {exc}"

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0 or not stdout:
        return None, stderr[:200] or f"ffprobe 返回码 {result.returncode}"

    try:
        info = json.loads(stdout)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None, "ffprobe 输出不是合法 JSON"

    fps = width = height = 0
    duration = 0.0
    try:
        for stream in info.get("streams") or []:
            if stream.get("codec_type") != "video":
                continue
            # avg_frame_rate 可能为 0/0，回退到 r_frame_rate
            fps = _parse_frame_rate(stream.get("avg_frame_rate")) or _parse_frame_rate(stream.get("r_frame_rate"))
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            duration = float(stream.get("duration") or 0.0)
            break
        fmt = info.get("format") or {}
        duration = duration or float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError) as exc:
        return None, f"ffprobe 字段解析失败: {exc}"

    info_dict = {"fps": fps, "duration": duration, "width": width, "height": height}
    if not _complete(info_dict):
        return None, f"指标不完整: {info_dict}"
    return info_dict, ""


def _probe_with_opencv(video_path: str) -> tuple:
    """用 OpenCV 读取视频信息，返回 (info|None, 失败原因)。"""
    try:
        import cv2
    except Exception as exc:
        return None, f"OpenCV 不可用: {exc}"

    cap = None
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None, "cv2.VideoCapture 打开失败"
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    except Exception as exc:
        return None, f"OpenCV 读取异常: {exc}"
    finally:
        if cap is not None:
            cap.release()

    duration = (frames / fps) if fps > 0 and frames > 0 else 0.0
    info_dict = {"fps": fps, "duration": duration, "width": width, "height": height}
    if not _complete(info_dict):
        return None, f"指标不完整: {info_dict}"
    return info_dict, ""


def _resolve_video(task_dir: str, step_inputs: dict) -> str:
    """解析视频路径：优先节点连线输入，回退扫描 cache 中的视频文件。"""
    raw = step_inputs.get("video", "")
    if raw:
        p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
        if os.path.isfile(p):
            return p

    cache_dir = os.path.join(task_dir, "cache")
    if os.path.isdir(cache_dir):
        for f in sorted(os.listdir(cache_dir)):
            if f.startswith("input_video") and f.lower().endswith(_VIDEO_EXTS):
                return os.path.join(cache_dir, f)
        for f in sorted(os.listdir(cache_dir)):
            if f.lower().endswith(_VIDEO_EXTS):
                return os.path.join(cache_dir, f)
    return ""


class S_GetVideoInfo(BaseStep):
    step_id = "s_get_video_info"
    step_name = "获取视频信息"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 本节点不落盘、无产物，恒为 False 表示每次都需要执行
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        return bool(_resolve_video(task_dir, step_inputs))

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        video_path = _resolve_video(task_dir, step_inputs)
        if not video_path:
            raise FileNotFoundError("未连接视频输入或缓存中未找到视频文件。")

        if callback:
            callback(10, f"视频: {os.path.basename(video_path)}")

        if cancel_callback is not None:
            cancel_callback()

        # --- 1. 优先 ffmpeg ---
        if callback:
            callback(30, "读取视频信息（ffmpeg）...")
        info, ff_err = _probe_with_ffmpeg(video_path)
        source = "ffmpeg"

        # --- 2. 失败回退 OpenCV ---
        if info is None:
            if callback:
                callback(60, f"ffmpeg 读取失败（{ff_err}），回退 OpenCV...")
            info, cv_err = _probe_with_opencv(video_path)
            source = "opencv"
        else:
            cv_err = ""

        # --- 3. 两者都失败则报错 ---
        if info is None:
            raise RuntimeError(
                "无法获取视频信息：ffmpeg 与 OpenCV 均失败。"
                f"ffmpeg: {ff_err or '未知原因'}；OpenCV: {cv_err or '未知原因'}"
            )

        if cancel_callback is not None:
            cancel_callback()

        fps_text = _fmt_number(info["fps"])
        duration_text = _fmt_number(info["duration"])
        width_text = str(int(info["width"]))
        height_text = str(int(info["height"]))

        if callback:
            callback(100, f"[{source}] {width_text}x{height_text} @ {fps_text}fps, 时长 {duration_text}s")

        return {
            "artifacts": [],
            "outputs": {
                "fps": fps_text,
                "duration": duration_text,
                "width": width_text,
                "height": height_text,
            },
        }
