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

# 视频编码参数统一由 backend/utils/video_encoder.py 提供（读取全局 video.gpu_accel）。
# 这里保留旧名称的引用，避免各处 import 失效。
from backend.utils.video_encoder import (  # noqa: F401
    X264_SPEED_PRESETS,
    NVENC_SPEED_PRESETS,
    QUALITY_CRF,
    build_video_encode_args,
    get_encoder_args,
    gpu_accel_enabled,
)


def _guarded(cmd: list) -> list:
    """为 ffmpeg 命令统一附加线程/封装队列限制（幂等）。"""
    from backend.utils.ffmpeg_guard import apply_resource_args
    return apply_resource_args(list(cmd))


def get_ffmpeg_timeout(default: float = 600) -> float:
    """读取全局配置中的 ffmpeg 超时时间（秒）"""
    try:
        val = float(config.get("video.ffmpeg_timeout", default) or default)
        return val if val > 0 else default
    except Exception:
        return default


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


def prepare_bgm(bgm_path: str, target_duration: float, output_path: str, loop: bool = True) -> str:
    """准备背景音乐，使其匹配目标时长
    
    如果BGM比目标时长短，则按 loop 决定是否循环播放；如果更长，则裁剪。
    """
    bgm_duration = get_audio_duration(bgm_path)
    
    # 计算循环次数
    loop_count = math.ceil(target_duration / bgm_duration) - 1
    
    # 构建ffmpeg命令
    if loop and loop_count > 0:
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count),
            "-i", bgm_path,
            "-t", str(target_duration),
            "-c:a", "pcm_s16le",
            output_path
        ]
    else:
        # 未开启循环，或 BGM 本身够长：按目标时长裁剪（不足部分保持静音）
        cmd = [
            "ffmpeg", "-y",
            "-i", bgm_path,
            "-t", str(target_duration),
            "-c:a", "pcm_s16le",
            output_path
        ]
    
    result = subprocess.run(_guarded(cmd), capture_output=True, text=True, timeout=get_ffmpeg_timeout())
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
    
    result = subprocess.run(_guarded(cmd), capture_output=True, text=True, timeout=get_ffmpeg_timeout())
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
    
    result = subprocess.run(_guarded(cmd), capture_output=True, text=True, timeout=get_ffmpeg_timeout())
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
    bgm_fade_in: float | None = None,
    bgm_fade_out: float | None = None,
    dub_fade_in: float | None = None,
    dub_fade_out: float | None = None,
    original_vol: float = 1.0,
    original_fade_in: float = 0.0,
    original_fade_out: float = 0.0,
    limiter: bool = True,
) -> str:
    """核心混音函数：将原始视频音频 + BGM + 配音混合为最终输出（分轨独立音量/淡变）

    混音语义与「音轨混响」节点（pydub overlay）对齐：
    - 各路音量已由 volume 参数显式给定，故关闭 amix 的自动归一化（normalize=0），
      避免「输入越多每路越轻」使参数失真；
    - 关闭自动归一化后峰值可能超限，默认在末端串一级 alimiter 限幅保护；
    - 音量与淡入淡出按轨独立，原声 / BGM / 配音互不影响。
    
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
        bgm_fade_in / bgm_fade_out: BGM 淡入/淡出（秒），None 时回退到 fade_in/fade_out
        dub_fade_in / dub_fade_out: 配音淡入/淡出（秒），None 时回退到 fade_in/fade_out
        original_vol: 原视频音轨音量倍数（1.0=原始）
        original_fade_in / original_fade_out: 原视频音轨淡入/淡出（秒），默认 0（与历史行为一致）
        limiter: 混音末端是否加 alimiter 限幅（关闭 amix 归一化后防止削顶）
    
    Returns:
        输出文件路径
    """
    # 获取视频时长
    duration = get_video_duration(video_path)
    
    # 检查视频是否有音频流
    has_audio = _video_has_audio(video_path)
    
    # 分轨淡变：未单独指定时回退到通用 fade_in/fade_out（保持旧配置行为不变）
    bgm_fade_in = fade_in if bgm_fade_in is None else bgm_fade_in
    bgm_fade_out = fade_out if bgm_fade_out is None else bgm_fade_out
    dub_fade_in = fade_in if dub_fade_in is None else dub_fade_in
    dub_fade_out = fade_out if dub_fade_out is None else dub_fade_out

    def _track_filter(volume, fin, fout) -> str:
        """生成单轨的 volume + afade 滤镜串（音量与淡变按轨独立）。"""
        parts = [f"volume={volume}"]
        if fin and float(fin) > 0:
            parts.append(f"afade=t=in:d={float(fin)}")
        if fout and float(fout) > 0:
            parts.append(f"afade=t=out:st={max(0.0, duration - float(fout))}:d={float(fout)}")
        return ",".join(parts)

    use_original = bool(has_audio and not mute_original)
    original_needs_filter = (
        float(original_vol) != 1.0
        or float(original_fade_in or 0) > 0
        or float(original_fade_out or 0) > 0
    )

    # Build inputs and filters
    inputs = [video_path]
    filter_parts = []

    # 原声（可选）：独立音量 + 淡变；未配置时保持 [0:a] 原样，行为与历史一致
    orig_label = "[0:a]"
    if use_original and original_needs_filter:
        filter_parts.append(
            f"[0:a]{_track_filter(original_vol, original_fade_in, original_fade_out)}[orig]"
        )
        orig_label = "[orig]"
    
    if bgm_path and dub_path:
        # 三轨混合：原始 + BGM + 配音
        inputs.extend([bgm_path, dub_path])
        
        # BGM滤镜链：音量 + 淡入淡出（分轨独立参数）
        filter_parts.append(f"[1:a]{_track_filter(bgm_vol, bgm_fade_in, bgm_fade_out)}[bgm]")
        
        # 配音滤镜链：音量 + 淡入淡出（分轨独立参数）
        filter_parts.append(f"[2:a]{_track_filter(dub_vol, dub_fade_in, dub_fade_out)}[dub]")
        
        # 混合三轨
        if has_audio and not mute_original:
            filter_parts.append(f"{orig_label}[bgm][dub]amix=inputs=3:duration=first:dropout_transition=3:normalize=0[mixed]")
        else:
            # 视频无音频或静音原始：只混 BGM + 配音
            filter_parts.append("[bgm][dub]amix=inputs=2:duration=first:dropout_transition=3:normalize=0[mixed]")
        
    elif bgm_path:
        # 两轨混合：原始 + BGM
        inputs.append(bgm_path)
        
        filter_parts.append(f"[1:a]{_track_filter(bgm_vol, bgm_fade_in, bgm_fade_out)}[bgm]")
        if has_audio and not mute_original:
            filter_parts.append(f"{orig_label}[bgm]amix=inputs=2:duration=first:dropout_transition=3:normalize=0[mixed]")
        else:
            # 视频无音频或静音原始：直接用 BGM
            filter_parts.append("[bgm]acopy[mixed]")
        
    elif dub_path:
        # 两轨混合：原始 + 配音
        inputs.append(dub_path)
        
        filter_parts.append(f"[1:a]{_track_filter(dub_vol, dub_fade_in, dub_fade_out)}[dub]")
        if has_audio and not mute_original:
            filter_parts.append(f"{orig_label}[dub]amix=inputs=2:duration=first:dropout_transition=3:normalize=0[mixed]")
        else:
            # 视频无音频或静音原始：直接用配音
            filter_parts.append("[dub]acopy[mixed]")
    
    else:
        # 无额外音轨：原声无需处理则直接复制；需要处理则走滤镜链只处理原声
        if not (use_original and original_needs_filter):
            output_settings = get_audio_output_settings()
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", f"{output_settings['bitrate']}k",
                output_path
            ]
            result = subprocess.run(_guarded(cmd), capture_output=True, text=True, timeout=get_ffmpeg_timeout())
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg failed: {result.stderr}")
            return output_path
        filter_parts.append(f"{orig_label}acopy[mixed]")

    # 关闭 amix 自动归一化后峰值可能超限，末端统一加一级限幅保护（level=0 表示不做自动增益）
    if limiter:
        filter_parts.append("[mixed]alimiter=limit=0.95:level=0[outmix]")
        mix_label = "[outmix]"
    else:
        mix_label = "[mixed]"

    # 构建完整命令
    filter_complex = ";\n".join(filter_parts)
    cmd = [
        "ffmpeg", "-y",
        *sum([["-i", inp] for inp in inputs], []),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", mix_label,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        # 限制封装队列，避免多音轨混流时队列无界增长导致内存暴涨
        "-max_muxing_queue_size", "4096",
        "-nostats",
        output_path
    ]

    result = subprocess.run(_guarded(cmd), capture_output=True, text=True, timeout=get_ffmpeg_timeout())
    if result.returncode != 0:
        # 如果使用了 [0:a] 但失败，可能是音频流损坏，去掉原始音频重试
        if has_audio and "[0:a]" in filter_complex and (bgm_path or dub_path):
            print(f"  ⚠ 原始音频流异常，去掉后重试...")
            return mix_audio(
                video_path, bgm_path, dub_path,
                bgm_vol, dub_vol, fade_in, fade_out, output_path,
                target_lufs, mute_original=True,
                bgm_fade_in=bgm_fade_in, bgm_fade_out=bgm_fade_out,
                dub_fade_in=dub_fade_in, dub_fade_out=dub_fade_out,
                original_vol=original_vol,
                original_fade_in=original_fade_in, original_fade_out=original_fade_out,
                limiter=limiter,
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

    result = subprocess.run(_guarded(cmd), capture_output=True, text=True, timeout=get_ffmpeg_timeout())
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
    callback=None,
    cancel_callback=None,
    threads: int = 0,
) -> str:
    """带字幕烧录的视频编码（重编码，CPU 密集）。

    Args:
        video_path: 输入视频路径
        ass_path: ASS字幕文件路径
        quality: 质量预设 ("copy", "high", "medium", "low")
        output_path: 输出视频路径
        encode_preset: 编码速度预设（None 则读全局配置 video.encode_preset）
        gpu_accel: 是否显卡加速（None 则读全局配置 video.gpu_accel）
        timeout: 超时时间秒（None 则读全局配置 video.ffmpeg_timeout）
        callback: 进度回调 ``(percent, message)``
        cancel_callback: 协作取消回调，返回 True 时终止 ffmpeg
        threads: 编解码 / 滤镜线程上限，0 表示交给 ffmpeg 自动决定

    资源保护（长高清视频烧录曾因无限制吃满 CPU / 内存而表现为卡死）：
    - 改用 ``run_ffmpeg_with_progress`` 流式执行替代 ``subprocess.run``：
      进度输出逐行消费（不再整段攒进内存），并支持进度上报与协作取消；
    - ``-threads`` / ``-filter_threads`` 限制编码与字幕滤镜线程，不再吃满全部 CPU；
    - ``-max_muxing_queue_size`` 限制封装队列，防止队列无界增长导致内存暴涨；
    - ``-nostats`` 抑制每秒统计行，避免长视频 stderr 无界累积。

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

    # 时长用于进度百分比（探测失败时进度保持不动，不影响执行）
    try:
        duration = get_video_duration(video_path)
    except Exception:
        duration = 0.0

    # 构建ffmpeg命令
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"subtitles='{escaped_ass}'",
        *encoder_args,
        "-c:a", "aac",
        "-b:a", "192k",
        "-max_muxing_queue_size", "4096",
    ]
    if threads and threads > 0:
        cmd += ["-threads", str(threads), "-filter_threads", str(threads)]
    else:
        from backend.utils.ffmpeg_guard import resource_args
        cmd += [a for a in resource_args() if a not in ("-max_muxing_queue_size", "4096")]
    cmd += ["-progress", "pipe:1", "-nostats", output_path]

    # 延迟导入：video_ops 依赖本模块的 get_ffmpeg_timeout，模块级导入会形成循环导入
    from backend.utils.video_ops import run_ffmpeg_with_progress

    run_ffmpeg_with_progress(
        cmd, duration, callback, cancel_callback,
        timeout=float(timeout) if timeout else get_ffmpeg_timeout(),
        label="字幕烧录",
    )
    return output_path
