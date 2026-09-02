"""Video operation utilities using ffmpeg."""
import subprocess
import os
from typing import Optional


def get_video_duration(path: str) -> float:
    """Get video duration in seconds."""
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def extract_audio(video_path: str, audio_path: str):
    """Extract audio from video."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        audio_path
    ]
    subprocess.run(cmd, capture_output=True, timeout=120)


def extract_last_frame(video_path: str, output_path: str) -> str:
    """Use ffmpeg to extract the last frame of a video as an image.

    Returns the output image path on success. Raises RuntimeError on failure
    (missing ffmpeg, invalid video, or empty output).
    """
    if not video_path or not os.path.isfile(video_path):
        raise RuntimeError(f"extract_last_frame: 视频文件不存在: {video_path}")
    duration = get_video_duration(video_path)
    # 取倒数第 2 帧附近，避免恰好落点超出时长导致抽不到帧
    seek = max(0.0, duration - 0.04) if duration > 0 else 0.0
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seek:.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError("extract_last_frame: 未找到 ffmpeg，请先安装 ffmpeg。")
    except subprocess.TimeoutExpired:
        raise RuntimeError("extract_last_frame: 抽取尾帧超时（60s）。")
    if result.returncode != 0 or not os.path.exists(output_path):
        err = (result.stderr or result.stdout or "")[:400]
        raise RuntimeError(f"extract_last_frame: ffmpeg 失败: {err}")
    return output_path


def merge_audio_video(video_path: str, audio_path: str, output_path: str):
    """Merge audio track with video."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, timeout=600)
