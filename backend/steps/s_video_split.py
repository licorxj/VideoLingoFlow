"""s_video_split: Split video into segments with optional silence-based cutting."""
import json
import os
import subprocess
import struct
import wave
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


def _resolve_path(value, task_dir: str = "") -> str:
    if not value or not isinstance(value, str):
        return ""
    candidate = value.strip()
    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            return rel
    return ""


def _get_duration(file_path: str) -> float:
    """Get media duration in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


def _extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video as WAV for analysis."""
    from backend.utils.ffmpeg_guard import apply_resource_args
    cmd = apply_resource_args([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        output_path,
    ])
    subprocess.run(cmd, capture_output=True, timeout=300)
    return output_path


def _compute_rms_values(wav_path: str, window_ms: int = 100) -> list:
    """Compute RMS energy values per window from a WAV file."""
    try:
        with wave.open(wav_path, "rb") as wf:
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
    except Exception:
        return []

    samples = struct.unpack(f"<{len(raw)//2}h", raw)
    window_size = int(sample_rate * window_ms / 1000)
    rms_values = []
    for i in range(0, len(samples) - window_size + 1, window_size):
        chunk = samples[i:i + window_size]
        rms = (sum(s * s for s in chunk) / len(chunk)) ** 0.5
        rms_values.append(rms)
    return rms_values


def _find_silence_point(rms_values: list, target_sec: float, window_ms: int = 100,
                        search_range_sec: float = 10.0) -> float:
    """Find the quietest point near target_sec within search_range_sec."""
    if not rms_values:
        return target_sec

    target_idx = int(target_sec * 1000 / window_ms)
    search_range_idx = int(search_range_sec * 1000 / window_ms)
    start_idx = max(0, target_idx - search_range_idx)
    end_idx = min(len(rms_values) - 1, target_idx + search_range_idx)

    if start_idx >= end_idx:
        return target_sec

    min_idx = min(range(start_idx, end_idx + 1), key=lambda i: rms_values[i])
    return min_idx * window_ms / 1000.0


def _cut_video(video_path: str, output_path: str, start: float, duration: float) -> bool:
    """Cut a segment from video using ffmpeg stream copy (fast, no re-encode)."""
    from backend.utils.ffmpeg_guard import apply_resource_args
    cmd = apply_resource_args([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", video_path,
        "-t", f"{duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ])
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    return result.returncode == 0


# 时间段区间支持的起止分隔符（半角/全角波浪线、破折号及「至/到」）
_RANGE_SEPARATORS = ("～", "~", "—", "–", "-", "至", "到")


def _parse_time_token(token: str) -> float:
    """解析单个时间值，支持 `90`（秒）与 `1:30`（分:秒）两种写法。"""
    token = str(token).strip()
    if not token:
        raise ValueError("时间段格式错误，请按 起始秒-结束秒 填写，如 30-90。")
    try:
        if ":" in token:
            total = 0.0
            for part in token.split(":"):
                total = total * 60 + float(part)
            return total
        return float(token)
    except ValueError:
        raise ValueError(f"无法解析时间值「{token}」，请按 起始秒-结束秒 填写，如 30-90。")


def _parse_time_range(value, duration: float) -> tuple:
    """把用户输入的时间段区间解析为 (start, end)，并按视频实际时长裁剪。

    支持 `30-90`、`30~90`、`1:30-2:00` 等写法。
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError("请填写时间段，如 30-90（秒）。")

    parts = None
    for sep in _RANGE_SEPARATORS:
        if sep in text:
            parts = text.split(sep, 1)
            break
    if not parts:
        raise ValueError(f"时间段格式错误：「{text}」，请按 起始秒-结束秒 填写，如 30-90。")

    start = _parse_time_token(parts[0])
    end = _parse_time_token(parts[1])
    if start < 0 or end < 0:
        raise ValueError("时间段不能为负数。")
    if start >= duration:
        raise ValueError(f"起始时间 {start:.1f}s 超出视频时长 {duration:.1f}s。")

    end = min(end, duration)
    if end - start < 0.05:
        raise ValueError(f"时间段过短（{end - start:.2f}s），请调整区间。")
    return start, end


def _cut_video_precise(video_path: str, output_path: str, start: float, duration: float) -> bool:
    """精准切割：重新编码，切点帧精确（用于「按时间段」模式）。

    与流拷贝不同，这里对视频重新编码，``-ss`` 放在 ``-i`` 前并显式开启
    ``-accurate_seek``，确保起始帧严格落在指定时间点上。视频编码参数经
    ``build_video_encode_args`` 构建，自动遵循全局「显卡加速」设置
    （开启则使用 NVENC 硬编码，否则 libx264 软编码）。
    """
    from backend.utils.ffmpeg_guard import apply_resource_args
    from backend.utils.video_encoder import build_video_encode_args

    if os.path.isfile(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    video_args = build_video_encode_args("libx264", crf=18, preset="medium")
    cmd = apply_resource_args([
        "ffmpeg", "-y",
        "-accurate_seek",
        "-ss", f"{start:.3f}",
        "-i", video_path,
        "-t", f"{duration:.3f}",
        *video_args,
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ])
    result = subprocess.run(cmd, capture_output=True, timeout=3600)
    return (
        result.returncode == 0
        and os.path.isfile(output_path)
        and os.path.getsize(output_path) > 0
    )


class S_VideoSplit(BaseStep):
    step_id = "s_video_split"
    step_name = "视频切割"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        output_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(output_dir):
            return False
        return any(f.startswith(f"split_{node_id}_") for f in os.listdir(output_dir))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. Read config ---
        split_mode = node_config.get("split_mode", "count")
        if isinstance(split_mode, list):
            split_mode = split_mode[0] if split_mode else "count"
        try:
            segment_count = max(1, int(float(node_config.get("segment_count", 2) or 2)))
        except (TypeError, ValueError):
            segment_count = 2
        try:
            segment_duration = float(node_config.get("segment_duration", 60) or 60)
        except (TypeError, ValueError):
            segment_duration = 60.0
        use_silence = node_config.get("use_silence", False)
        try:
            output_index = int(float(node_config.get("output_index", 1) or 1))
        except (TypeError, ValueError):
            output_index = 1
        time_range = node_config.get("time_range", "")
        if isinstance(time_range, list):
            time_range = time_range[0] if time_range else ""
        is_range_mode = split_mode == "range"

        # --- 2. Resolve inputs ---
        video_path = _resolve_path(step_inputs.get("video", ""), task_dir)
        if not video_path:
            raise FileNotFoundError("未连接视频输入。")

        audio_path = _resolve_path(step_inputs.get("audio", ""), task_dir)

        # --- 3. Get video duration ---
        duration = _get_duration(video_path)
        if duration <= 0:
            raise ValueError("无法获取视频时长。")
        if callback:
            callback(10, f"视频时长: {duration:.1f}秒")

        # --- 4. Compute cut points (range 模式由用户直接指定区间) ---
        if is_range_mode:
            raw_points = []
        elif split_mode == "count":
            raw_points = [i * duration / segment_count for i in range(1, segment_count)]
        else:
            if segment_duration <= 0:
                raise ValueError("每段时长必须大于 0。")
            raw_points = []
            t = segment_duration
            while t < duration:
                raw_points.append(t)
                t += segment_duration

        # --- 5. Adjust to silence points if requested ---
        if use_silence and raw_points:
            if callback:
                callback(20, "分析音频寻找静音点...")

            # If no separate audio input, extract from video
            if not audio_path:
                audio_path = os.path.join(task_dir, "cache", f"_split_audio_{node_id}.wav")
                os.makedirs(os.path.dirname(audio_path), exist_ok=True)
                _extract_audio(video_path, audio_path)

            rms_values = _compute_rms_values(audio_path)
            if rms_values:
                adjusted = []
                for pt in raw_points:
                    adj = _find_silence_point(rms_values, pt)
                    adjusted.append(adj)
                    if callback:
                        callback(None, f"  切割点 {pt:.1f}s → {adj:.1f}s (静音)")
                raw_points = adjusted

        # Build all segments: [start, end]
        if is_range_mode:
            # 用户指定单个区间，输出唯一一段
            range_start, range_end = _parse_time_range(time_range, duration)
            segments = [(range_start, range_end)]
            output_index = 1
        else:
            boundaries = [0.0] + raw_points + [duration]
            segments = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]

        # --- 6. Validate output_index ---
        if output_index < 1 or output_index > len(segments):
            raise ValueError(f"序号 {output_index} 超出范围 (共 {len(segments)} 段)。")

        # --- 7. Cut the requested segment ---
        start, end = segments[output_index - 1]
        seg_duration = end - start
        if callback:
            if is_range_mode:
                callback(70, f"精准切割时间段: {start:.1f}s ~ {end:.1f}s")
            else:
                callback(70, f"切割第 {output_index}/{len(segments)} 段: {start:.1f}s ~ {end:.1f}s")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        ext = os.path.splitext(video_path)[1] or ".mp4"
        output_filename = f"split_{node_id}_{output_index}{ext}"
        output_path = os.path.join(output_dir, output_filename)

        # 时间段模式强制使用精准切割（重新编码，帧精确）；其余模式沿用流拷贝
        if is_range_mode:
            ok = _cut_video_precise(video_path, output_path, start, seg_duration)
        else:
            ok = _cut_video(video_path, output_path, start, seg_duration)
        if not ok:
            raise RuntimeError("ffmpeg 视频切割失败。")

        if callback:
            callback(100, f"完成: {output_filename}")

        return {
            "artifacts": [f"output/{output_filename}"],
            "outputs": {
                "video": f"output/{output_filename}",
                "text": (
                    f"时间段 {start:.1f}s ~ {end:.1f}s (时长 {seg_duration:.1f}s，精准切割)"
                    if is_range_mode
                    else f"第{output_index}段 ({start:.1f}s ~ {end:.1f}s)"
                ),
            },
        }
