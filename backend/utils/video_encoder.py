# -*- coding: utf-8 -*-
"""视频编码参数统一构建（全局「视频处理 → 使用显卡加速 (NVIDIA NVENC)」开关）。

所有需要 ffmpeg **重新编码视频**的节点都应通过本模块构建 ``-c:v`` 相关参数，
从而在全局设置 ``video.gpu_accel`` 开启时自动切换到 NVIDIA NVENC 硬编码，
关闭时回落到 CPU 软编码（libx264 / libx265 / ...）。

约定：
  - ``gpu_accel`` 传 None 时读取全局配置 ``video.gpu_accel``；
  - 仅 H.264/H.265 支持 NVENC（h264_nvenc / hevc_nvenc），
    VP9 / MPEG-4 等无对应硬编码器的格式自动保持软编码；
  - NVENC 不支持 ``-crf``，统一换算为 ``-rc vbr -cq <值> -b:v 0``。
"""
import re
import shutil
import subprocess
from typing import Optional

from backend.config.config_manager import config

# x264/x265 支持的编码速度预设
X264_SPEED_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower")
# NVENC (h264_nvenc / hevc_nvenc) 的速度预设映射
NVENC_SPEED_PRESETS = {
    "ultrafast": "p1", "superfast": "p2", "veryfast": "p2", "faster": "p3",
    "fast": "p4", "medium": "p5", "slow": "p6", "slower": "p7",
}
# 质量档位 -> CRF/CQ
QUALITY_CRF = {"high": 18, "medium": 23, "low": 28}
# 质量档位 -> mpeg4 的 -q:v（1-31，越小质量越高）
QUALITY_QSCALE = {"high": 2, "medium": 5, "low": 8}
# 支持 -crf / -cq 质量控制的编码器
CRF_CODECS = ("libx264", "libx265", "libvpx-vp9")
# 支持 -preset 的软编码器
PRESET_CODECS = ("libx264", "libx265")
# 软编码器 -> NVENC 硬编码器
NVENC_CODEC_MAP = {"libx264": "h264_nvenc", "libx265": "hevc_nvenc"}


def _to_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


# h264_nvenc 可用性探测结果（进程内缓存，None = 尚未探测）
_nvenc_available: Optional[bool] = None


def probe_nvenc_available(force: bool = False) -> bool:
    """实际编码一帧来确认 h264_nvenc 是否可用。

    仅查询 ``ffmpeg -encoders`` 列表并不可靠（驱动/显卡缺失时仍可能列出该编码器），
    因此这里真正跑一次极小分辨率的 h264_nvenc 编码，成功才算可用。
    结果在进程内缓存；``force=True`` 可强制重新探测。
    """
    global _nvenc_available
    if _nvenc_available is not None and not force:
        return _nvenc_available

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.04:r=25",
        "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p",
        "-frames:v", "1", "-f", "null", "-",
    ]
    ok = False
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30,
        )
        ok = proc.returncode == 0
        if not ok:
            detail = (proc.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
            print(f"[GPU] h264_nvenc 不可用: {detail[-1] if detail else 'unknown error'}")
    except FileNotFoundError:
        print("[GPU] 未找到 ffmpeg，h264_nvenc 不可用")
    except subprocess.TimeoutExpired:
        print("[GPU] h264_nvenc 探测超时，视为不可用")
    except Exception as e:
        print(f"[GPU] h264_nvenc 探测异常: {e}")

    _nvenc_available = ok
    return ok


def gpu_accel_enabled(explicit=None) -> bool:
    """是否启用显卡加速（NVIDIA NVENC）。

    Args:
        explicit: 显式值（节点配置）。为 None 时读取全局配置 ``video.gpu_accel``。

    开关开启但当前环境实际不支持 h264_nvenc 时降级为软编码，避免 ffmpeg 命令直接失败。
    """
    if explicit is None:
        explicit = config.get("video.gpu_accel", False)
    if isinstance(explicit, str):
        explicit = explicit.strip().lower() in ("true", "1", "yes", "on")
    if not explicit:
        return False
    if not probe_nvenc_available():
        print("[GPU] 已开启显卡加速但 h264_nvenc 不可用，本次改用软编码 (libx264)")
        return False
    return True


def _nvenc_preset(preset: str) -> str:
    """把 x264 预设名（或已是 p1~p7）归一为 NVENC 预设。"""
    s = str(preset or "").strip().lower()
    if s in NVENC_SPEED_PRESETS:
        return NVENC_SPEED_PRESETS[s]
    if re.fullmatch(r"p[1-7]", s):
        return s
    return "p5"


def _x264_preset(preset: str) -> str:
    """把预设名（x264 或 p1~p7）归一为 x264 预设。"""
    s = str(preset or "").strip().lower()
    if s in X264_SPEED_PRESETS:
        return s
    for k, v in NVENC_SPEED_PRESETS.items():
        if v == s:
            return k
    return "medium"


def build_video_encode_args(codec: str, quality=None, crf=None, preset=None,
                            gpu_accel=None, bitrate=None, allow_nvenc: bool = True) -> list:
    """构建 ffmpeg 视频编码参数，按全局设置决定是否使用 NVENC 硬编码。

    Args:
        codec: 目标软编码器（"copy" / "libx264" / "libx265" / "libvpx-vp9" / "mpeg4"
               / "h264_nvenc" / "hevc_nvenc"）。前两者在开启显卡加速时自动升级为 NVENC。
        quality: 质量档位（"high" / "medium" / "low"），crf 为空时生效。
        crf: 显式 CRF/CQ 值，优先于 quality。
        preset: 编码速度预设（x264 名或 p1~p7），为空则不传 -preset（用 ffmpeg 默认）。
        gpu_accel: 覆盖全局开关（None = 读全局配置 video.gpu_accel）。
        bitrate: 目标视频码率（如 "5M"），为空则不传。
        allow_nvenc: 是否允许把 libx264/libx265 自动升级为 NVENC。
            节点把编码器作为内部实现时应为 True；节点显式暴露编码器下拉、
            用户已明确选定 CPU 编码器时应为 False，避免覆盖用户选择。

    Returns:
        ffmpeg 参数列表，如 ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23", "-b:v", "0"]
    """
    codec = str(codec or "libx264").strip()
    if codec == "copy":
        return ["-c:v", "copy"]

    # 仅 H.264/H.265 有 NVENC 对应实现
    if allow_nvenc and gpu_accel_enabled(gpu_accel) and codec in NVENC_CODEC_MAP:
        codec = NVENC_CODEC_MAP[codec]
    is_nvenc = codec.endswith("_nvenc")

    args = ["-c:v", codec]

    # 目标质量：显式 crf 优先，其次质量档位
    cq = _to_int(crf)
    if cq is None and quality:
        q = str(quality).strip().lower()
        cq = QUALITY_CRF.get(q, _to_int(q))

    if is_nvenc:
        if preset:
            args += ["-preset", _nvenc_preset(preset)]
        if cq is not None:
            args += ["-rc", "vbr", "-cq", str(cq), "-b:v", "0"]
    elif codec in CRF_CODECS:
        if preset and codec in PRESET_CODECS:
            args += ["-preset", _x264_preset(preset)]
        if cq is not None:
            args += ["-crf", str(cq)]
            if codec == "libvpx-vp9":
                args += ["-b:v", "0"]
    elif codec == "mpeg4":
        args += ["-q:v", str(QUALITY_QSCALE.get(str(quality or "medium").strip().lower(), 5))]

    if bitrate:
        args += ["-b:v", str(bitrate)]
    return args


def get_encoder_args(quality: str, encode_preset: str = None, gpu_accel=None) -> list:
    """H.264 编码参数（字幕烧录等沿用的旧接口）。

    quality="copy" 时返回 ["-c:v", "copy"]；否则按全局配置决定
    h264_nvenc 或 libx264。速度预设与显卡开关为 None 时读取全局配置。
    """
    if quality == "copy":
        return ["-c:v", "copy"]

    if encode_preset is None:
        encode_preset = config.get("video.encode_preset", "medium")

    return build_video_encode_args(
        "libx264",
        quality=quality if quality in QUALITY_CRF else "medium",
        preset=encode_preset,
        gpu_accel=gpu_accel,
    )
