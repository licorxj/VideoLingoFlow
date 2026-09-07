"""Audio processing utilities for video workflow.

Provides BGM preparation (looping, trimming), volume adjustment,
fade in/out effects, and multi-track mixing via ffmpeg.
"""

import subprocess
import json
import math
import os
from backend.config.config_manager import config
from backend.utils.audio_segmenter import get_audio_output_settings

# x264 支持的编码速度预设
X264_SPEED_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower")
# NVENC (h264_nvenc) 的速度预设映射
NVENC_SPEED_PRESETS = {
    "ultrafast": "p1", "superfast": "p2", "veryfast": "p2", "faster": "p3",
    "fast": "p4", "medium": "p5", "slow": "p6", "slower": "p7",
}
# 质量档位对应的 CRF 值
QUALITY_CRF = {"high": 18, "medium": 23, "low": 28}


def get_ffmpeg_timeout(default: float = 600) -> float:
    """读取全局配置中的 ffmpeg 超时时间（秒）"""
    try:
        val = float(config.get("video.ffmpeg_timeout", default) or default)
        return val if val > 0 else default
    except Exception:
        return default


def get_encoder_args(quality: str, encode_preset: str = None, gpu_accel=None) -> list:
    """根据质量档位 + 全局配置构建视频编码参数。

    Args:
        quality: 质量预设 ("copy", "high", "medium", "low")
        encode_preset: 编码速度预设（None 则读全局配置 video.encode_preset）
        gpu_accel: 是否显卡加速（None 则读全局配置 video.gpu_accel）

    Returns:
        ffmpeg 编码参数列表，如 ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
    """
    if quality == "copy":
        return ["-c:v", "copy"]

    crf = QUALITY_CRF.get(quality, 23)

    if encode_preset is None:
        encode_preset = config.get("video.encode_preset", "medium")
    speed = str(encode_preset or "medium").lower()
    if speed not in X264_SPEED_PRESETS:
        speed = "medium"

    if gpu_accel is None:
        gpu_accel = config.get("video.gpu_accel", False)
    if isinstance(gpu_accel, str):
        gpu_accel = gpu_accel.lower() in ("true", "1", "yes")

    if gpu_accel:
        # NVIDIA NVENC 硬编码
        return [
            "-c:v", "h264_nvenc",
            "-preset", NVENC_SPEED_PRESETS.get(speed, "p5"),
            "-rc", "vbr", "-cq", str(crf), "-b:v", "0",
        ]
    return ["-c:v", "libx264", "-preset", speed, "-crf", str(crf)]


def get_audio_duration(audio_path: str) -> float:
    """获取音频文件时长（秒）"""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", audio_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=get_ffmpeg_timeout())
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def get_video_duration(video_path: str) -> float:
    """获取视频文件时长（秒）"""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=get_ffmpeg_timeout())
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def prepare_bgm(bgm_path: str, target_duration: float, output_path: str) -> str:
    """准备背景音乐，使其匹配目标时长
    
    如果BGM比目标时长短，则循环播放；如果更长，则裁剪。
    """
    bgm_duration = get_audio_duration(bgm_path)
    
    # 计算循环次数
    loop_count = math.ceil(target_duration / bgm_duration) - 1
    
    # 构建ffmpeg命令
    if loop_count > 0:
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count),
            "-i", bgm_path,
            "-t", str(target_duration),
            "-c:a", "pcm_s16le",
            output_path
        ]
    else:
        # BGM比目标时长长，直接裁剪，不使用-stream_loop
        cmd = [
            "ffmpeg", "-y",
            "-i", bgm_path,
            "-t", str(target_duration),
            "-c:a", "pcm_s16le",
            output_path
        ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=get_ffmpeg_timeout())
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")
    
    return output_path


def adjust_volume(audio_path: str, volume: float, output_path: str) -> str:
    """调整音频文件音量
    
    Args:
        audio_path: 输入音频路径
        volume: 音量倍数 (0.0 = 静音, 1.0 = 原始音量)
        output_path: 输出音频路径
    
    Returns:
        输出文件路径
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", audio_path,
        "-af", f"volume={volume}",
        "-c:a", "pcm_s16le",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=get_ffmpeg_timeout())
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")
    
    return output_path


def apply_fade(audio_path: str, fade_in: float, fade_out: float, duration: float, output_path: str) -> str:
    """应用淡入淡出效果
    
    Args:
        audio_path: 输入音频路径
        fade_in: 淡入时长（秒）
        fade_out: 淡出时长（秒）
        duration: 音频总时长（秒）
        output_path: 输出音频路径
    
    Returns:
        输出文件路径
    """
    # 构建afade滤镜
    filters = []
    
    if fade_in > 0:
        filters.append(f"afade=t=in:d={fade_in}")
    
    if fade_out > 0:
        fade_out_start = duration - fade_out
        filters.append(f"afade=t=out:st={fade_out_start}:d={fade_out}")
    
    if not filters:
        # 无淡入淡出效果，直接复制
        cmd = ["ffmpeg", "-y", "-i", audio_path, "-c:a", "pcm_s16le", output_path]
    else:
        filter_str = ",".join(filters)
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-af", filter_str,
            "-c:a", "pcm_s16le",
            output_path
        ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=get_ffmpeg_timeout())
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")
    
    return output_path


def _video_has_audio(video_path: str) -> bool:
    """检查视频文件是否包含音频流。"""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return "audio" in result.stdout
    except Exception:
        return False


def mix_audio(
    video_path: str,
    bgm_path: str | None,
    dub_path: str | None,
    bgm_vol: float,
    dub_vol: float,
    fade_in: float,
    fade_out: float,
    output_path: str,
    target_lufs: float = -16,
    mute_original: bool = False,
) -> str:
    """核心混音函数：将原始视频音频 + BGM + 配音混合为最终输出
    
    Args:
        video_path: 输入视频路径
        bgm_path: BGM音频路径（可选）
        dub_path: 配音音频路径（可选）
        bgm_vol: BGM音量倍数
        dub_vol: 配音音量倍数
        fade_in: 淡入时长（秒）
        fade_out: 淡出时长（秒）
        output_path: 输出视频路径
        target_lufs: 目响度目标（未使用，预留参数）
        mute_original: 是否静音原视频音频
    
    Returns:
        输出文件路径
    """
    # 获取视频时长
    duration = get_video_duration(video_path)
    
    # 检查视频是否有音频流
    has_audio = _video_has_audio(video_path)
    
    # Build inputs and filters
    inputs = [video_path]
    filter_parts = []
    
    if bgm_path and dub_path:
        # 三轨混合：原始 + BGM + 配音
        inputs.extend([bgm_path, dub_path])
        
        # BGM滤镜链：调整音量 + 淡入淡出
        bgm_filters = [f"volume={bgm_vol}"]
        if fade_in > 0:
            bgm_filters.append(f"afade=t=in:d={fade_in}")
        if fade_out > 0:
            bgm_filters.append(f"afade=t=out:st={duration - fade_out}:d={fade_out}")
        filter_parts.append(f"[1:a]{','.join(bgm_filters)}[bgm]")
        
        # 配音滤镜链：调整音量 + 淡入淡出
        dub_filters = [f"volume={dub_vol}"]
        if fade_in > 0:
            dub_filters.append(f"afade=t=in:d={fade_in}")
        if fade_out > 0:
            dub_filters.append(f"afade=t=out:st={duration - fade_out}:d={fade_out}")
        filter_parts.append(f"[2:a]{','.join(dub_filters)}[dub]")
        
        # 混合三轨
        if has_audio and not mute_original:
            filter_parts.append("[0:a][bgm][dub]amix=inputs=3:duration=first:dropout_transition=3[mixed]")
        else:
            # 视频无音频或静音原始：只混 BGM + 配音
            filter_parts.append("[bgm][dub]amix=inputs=2:duration=first:dropout_transition=3[mixed]")
        
    elif bgm_path:
        # 两轨混合：原始 + BGM
        inputs.append(bgm_path)
        
        bgm_filters = [f"volume={bgm_vol}"]
        if fade_in > 0:
            bgm_filters.append(f"afade=t=in:d={fade_in}")
        if fade_out > 0:
            bgm_filters.append(f"afade=t=out:st={duration - fade_out}:d={fade_out}")
        filter_parts.append(f"[1:a]{','.join(bgm_filters)}[bgm]")
        if has_audio and not mute_original:
            filter_parts.append("[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=3[mixed]")
        else:
            # 视频无音频或静音原始：直接用 BGM
            filter_parts.append("[bgm]acopy[mixed]")
        
    elif dub_path:
        # 两轨混合：原始 + 配音
        inputs.append(dub_path)
        
        dub_filters = [f"volume={dub_vol}"]
        if fade_in > 0:
            dub_filters.append(f"afade=t=in:d={fade_in}")
        if fade_out > 0:
            dub_filters.append(f"afade=t=out:st={duration - fade_out}:d={fade_out}")
        filter_parts.append(f"[1:a]{','.join(dub_filters)}[dub]")
        if has_audio and not mute_original:
            filter_parts.append("[0:a][dub]amix=inputs=2:duration=first:dropout_transition=3[mixed]")
        else:
            # 视频无音频或静音原始：直接用配音
            filter_parts.append("[dub]acopy[mixed]")
    
    else:
        # 无额外音轨，直接复制
        output_settings = get_audio_output_settings()
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", f"{output_settings['bitrate']}k",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=get_ffmpeg_timeout())
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")
        return output_path
    
    # 构建完整命令
    filter_complex = ";\n".join(filter_parts)
    cmd = [
        "ffmpeg", "-y",
        *sum([["-i", inp] for inp in inputs], []),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[mixed]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=get_ffmpeg_timeout())
    if result.returncode != 0:
        # 如果使用了 [0:a] 但失败，可能是音频流损坏，去掉原始音频重试
        if has_audio and "[0:a]" in filter_complex and (bgm_path or dub_path):
            print(f"  ⚠ 原始音频流异常，去掉后重试...")
            return mix_audio(
                video_path, bgm_path, dub_path,
                bgm_vol, dub_vol, fade_in, fade_out, output_path,
                target_lufs, mute_original=True,
            )
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")
    
    return output_path


def mute_video_audio(video_path: str, output_path: str) -> str:
    """将视频音频静音
    
    Args:
        video_path: 输入视频路径
        output_path: 输出视频路径
    
    Returns:
        输出文件路径
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-an",
        "-c:v", "copy",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=get_ffmpeg_timeout())
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")
    
    return output_path


def encode_video_with_quality(
    video_path: str,
    ass_path: str,
    quality: str,
    output_path: str,
    encode_preset: str = None,
    gpu_accel=None,
    timeout: float = None,
) -> str:
    """带字幕烧录的视频编码

    Args:
        video_path: 输入视频路径
        ass_path: ASS字幕文件路径
        quality: 质量预设 ("copy", "high", "medium", "low")
        output_path: 输出视频路径
        encode_preset: 编码速度预设（None 则读全局配置 video.encode_preset）
        gpu_accel: 是否显卡加速（None 则读全局配置 video.gpu_accel）
        timeout: 超时时间秒（None 则读全局配置 video.ffmpeg_timeout）

    Returns:
        输出文件路径
    """
    # "copy"模式无法使用字幕滤镜，回退到"medium"
    if quality == "copy":
        quality = "medium"

    # 构建编码参数（编码速度 / 显卡加速由配置或参数决定）
    encoder_args = get_encoder_args(quality, encode_preset=encode_preset, gpu_accel=gpu_accel)

    # 转义ASS路径中的特殊字符（用于ffmpeg subtitles滤镜）
    escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")

    # 构建ffmpeg命令
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"subtitles='{escaped_ass}'",
        *encoder_args,
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=float(timeout) if timeout else get_ffmpeg_timeout(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")

    return output_path
