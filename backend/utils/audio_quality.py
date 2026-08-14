# -*- coding: utf-8 -*-
"""音频质量参数解析与 ffmpeg 编码工具。

优先级约定：节点优先、全局设置兜底。
供音频分离 / 人声分离等节点统一使用。
"""
import os
import subprocess
from typing import Callable, Optional


def resolve_audio_quality(node_config: Optional[dict] = None) -> dict:
    """节点优先、全局兜底：返回 {format, sample_rate, bit_depth, channels, bitrate}。

    - 节点 config 显式设置的值优先（含空字符串视为未设置）
    - 未设置时读取全局音频输出质量设置
    """
    from backend.utils.audio_segmenter import get_audio_output_settings
    node_config = node_config or {}
    global_audio = get_audio_output_settings()

    fmt = (str(node_config.get("format") or "").strip()) or str(global_audio.get("format") or "wav")
    sample_rate = (str(node_config.get("sample_rate") or "").strip()) or str(global_audio.get("sample_rate") or 44100)
    try:
        bit_depth = int(node_config.get("bit_depth") or global_audio.get("bit_depth") or 16)
    except (TypeError, ValueError):
        bit_depth = int(global_audio.get("bit_depth") or 16)
    try:
        channels = int(node_config.get("channels") or global_audio.get("channels") or 2)
    except (TypeError, ValueError):
        channels = int(global_audio.get("channels") or 2)
    bitrate = node_config.get("bitrate") or global_audio.get("bitrate")

    return {
        "format": fmt,
        "sample_rate": sample_rate,
        "bit_depth": bit_depth,
        "channels": channels,
        "bitrate": bitrate,
    }


def ffmpeg_encode_args(quality: dict) -> list:
    """根据质量参数构造 ffmpeg 编码参数（-acodec / -ar / -ac / -b:a）。"""
    fmt = (quality or {}).get("format", "wav")
    bit_depth = int((quality or {}).get("bit_depth") or 16)
    bitrate = (quality or {}).get("bitrate")

    if fmt == "wav":
        codec = "pcm_s24le" if bit_depth >= 24 else "pcm_s16le"
    elif fmt == "flac":
        codec = "flac"
    elif fmt == "m4a":
        codec = "aac"
    else:
        codec = "libmp3lame"

    args = [
        "-acodec", codec,
        "-ar", str((quality or {}).get("sample_rate") or 44100),
        "-ac", str(int((quality or {}).get("channels") or 2)),
    ]
    if fmt in ("mp3", "m4a") and bitrate:
        args += ["-b:a", f"{int(bitrate)}k"]
    return args


def reencode_audio(src: str, dst: str, quality: dict, timeout: int = 600,
                   callback: Optional[Callable] = None) -> None:
    """按质量参数用 ffmpeg 将 src 转码输出到 dst（目录由调用方保证存在）。"""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", src, *ffmpeg_encode_args(quality), dst]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Exception(f"音频转码超时（{timeout}s）: {dst}")
    except FileNotFoundError:
        raise Exception("ffmpeg not found. Please install ffmpeg or place ffmpeg.exe in the venv Scripts directory.")
    if result.returncode != 0:
        lines = (result.stderr or "").strip().split("\n")
        error_lines = [ln.strip() for ln in lines if ln.strip() and not (
            ln.startswith("ffmpeg version") or ln.startswith("  built with")
            or ln.startswith("  configuration:") or ln.startswith("  lib"))]
        raise Exception("ffmpeg failed:\n" + "\n".join(error_lines[-5:]))
