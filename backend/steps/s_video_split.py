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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


def _extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video as WAV for analysis."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        output_path,
    ]
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
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", video_path,
        "-t", f"{duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    return result.returncode == 0


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
        segment_count = int(node_config.get("segment_count", 2))
        segment_duration = float(node_config.get("segment_duration", 60))
        use_silence = node_config.get("use_silence", False)
        output_index = int(node_config.get("output_index", 1))

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

        # --- 4. Compute cut points ---
        if split_mode == "count":
            raw_points = [i * duration / segment_count for i in range(1, segment_count)]
        else:
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
        boundaries = [0.0] + raw_points + [duration]
        segments = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]

        # --- 6. Validate output_index ---
        if output_index < 1 or output_index > len(segments):
            raise ValueError(f"序号 {output_index} 超出范围 (共 {len(segments)} 段)。")

        # --- 7. Cut the requested segment ---
        start, end = segments[output_index - 1]
        seg_duration = end - start
        if callback:
            callback(70, f"切割第 {output_index}/{len(segments)} 段: {start:.1f}s ~ {end:.1f}s")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        ext = os.path.splitext(video_path)[1] or ".mp4"
        output_filename = f"split_{node_id}_{output_index}{ext}"
        output_path = os.path.join(output_dir, output_filename)

        ok = _cut_video(video_path, output_path, start, seg_duration)
        if not ok:
            raise RuntimeError("ffmpeg 视频切割失败。")

        if callback:
            callback(100, f"完成: {output_filename}")

        return {
            "artifacts": [f"output/{output_filename}"],
            "outputs": {
                "video": f"output/{output_filename}",
                "text": f"第{output_index}段 ({start:.1f}s ~ {end:.1f}s)",
            },
        }
