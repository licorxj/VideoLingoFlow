"""音频变速工具函数

提供高质量的音频变速处理，优先保证两点：
1. 变速不变音高
2. 不主动降低采样率/声道
"""
import os
import subprocess
import shutil
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 检查可用的变速后端
_HAS_RUBBERBAND = False
try:
    import rubberband
    _HAS_RUBBERBAND = True
except ImportError:
    pass

_HAS_NUMPY = False
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    pass

_HAS_SOUNDFILE = False
try:
    import soundfile as sf
    _HAS_SOUNDFILE = True
except ImportError:
    pass

_HAS_PYDUB = False
try:
    from pydub import AudioSegment
    _HAS_PYDUB = True
except ImportError:
    pass

@lru_cache(maxsize=1)
def _ffmpeg_path() -> Optional[str]:
    """惰性解析 ffmpeg 可执行文件路径；找不到返回 None。

    模块导入时 PATH 可能尚未就绪（如子进程/工作线程场景），
    因此在首次调用时才探测，而不是导入时一次性判定。
    """
    return shutil.which("ffmpeg")


def _ffmpeg_available() -> bool:
    return _ffmpeg_path() is not None


# 兼容旧引用：仅作为模块级快照，运行时判断请用 _ffmpeg_available()
_HAS_FFMPEG = shutil.which("ffmpeg") is not None


@lru_cache(maxsize=8)
def _ffmpeg_has_filter(filter_name: str) -> bool:
    """检测当前 ffmpeg 是否内置指定滤镜。"""
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return False
        return filter_name in result.stdout
    except Exception:
        return False


def get_audio_duration(audio_path: str) -> float:
    """获取音频文件时长（秒），优先用 soundfile，回退用 wave"""
    try:
        if _HAS_SOUNDFILE:
            info = sf.info(audio_path)
            return info.duration
    except Exception:
        pass
    try:
        import wave
        with wave.open(audio_path, 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0:
                return frames / rate
    except Exception:
        pass
    return 0.0


def adjust_audio_speed(input_path: str, output_path: str, speed_factor: float) -> float:
    """变速不变音高，返回变速后的真实时长(秒)。

    Args:
        input_path: 输入音频文件路径
        output_path: 输出音频文件路径
        speed_factor: 变速倍数，>1.0 加速，<1.0 减速

    Returns:
        变速后音频的实际时长（秒）
    """
    if abs(speed_factor - 1.0) < 0.001:
        shutil.copy2(input_path, output_path)
        return get_audio_duration(output_path)

    # 优先使用精确版本（librosa/rubberband 变速不变音高）
    try:
        actual_dur, _ = adjust_audio_speed_precise(input_path, output_path, speed_factor)
        if actual_dur > 0 and os.path.exists(output_path):
            return actual_dur
    except Exception as e:
        logger.debug(f"adjust_audio_speed_precise 失败，回退: {e}")

    # 回退: ffmpeg atempo（也是变速不变音高）
    if _ffmpeg_available():
        try:
            success = _adjust_with_ffmpeg(input_path, output_path, speed_factor)
            if success:
                return get_audio_duration(output_path)
        except Exception as e:
            logger.debug(f"ffmpeg 变速失败: {e}")

    raise RuntimeError(
        "没有可用的保真变速后端（需要 librosa、rubberband 或 ffmpeg），"
        "已拒绝使用会变调的 numpy 重采样回退"
    )


def _adjust_with_rubberband(input_path: str, output_path: str, speed_factor: float) -> bool:
    """使用 pyrubberband 做高质量 WSOLA 变速"""
    import rubberband
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(input_path)
    # rubberband expects shape (channels, samples) for multi-channel
    if data.ndim == 1:
        data_2d = data[np.newaxis, :]
    else:
        data_2d = data.T

    stretched = rubberband.stretch(data_2d, ratio=1.0 / speed_factor, samplerate=sr)
    if stretched.ndim > 1:
        stretched = stretched.T

    sf.write(output_path, stretched, sr, subtype='PCM_16')
    return True


def _adjust_with_ffmpeg(input_path: str, output_path: str, speed_factor: float) -> bool:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return False
    output_ext = Path(output_path).suffix.lower()
    preferred_backend = _select_ffmpeg_speed_backend(speed_factor)
    backends = [preferred_backend]
    if preferred_backend != "atempo":
        backends.append("atempo")

    for backend in backends:
        filter_str = _build_ffmpeg_speed_filter(speed_factor, backend=backend)
        cmd = [ffmpeg, "-y", "-i", input_path, "-vn", "-sn", "-dn", "-filter:a", filter_str]

        # 中间 WAV 文件优先使用 24-bit PCM，减少多次处理时的量化损失。
        if output_ext == ".wav":
            cmd += ["-c:a", "pcm_s24le"]
        elif output_ext == ".flac":
            cmd += ["-c:a", "flac"]

        cmd.append(output_path)
        logger.info("ffmpeg speed backend=%s speed_factor=%.4f", backend, speed_factor)
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0 and os.path.exists(output_path):
            return True
        logger.debug("ffmpeg backend %s failed: %s", backend, result.stderr[-500:])

    return False


def _build_atempo_chain(speed_factor: float) -> list:
    """构建 ffmpeg atempo 滤镜链，处理 atempo 的 [0.5, 100.0] 范围限制"""
    filters = []
    remaining = speed_factor

    while remaining > 100.0:
        filters.append("atempo=100.0")
        remaining /= 100.0

    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5

    if abs(remaining - 1.0) > 0.001:
        filters.append(f"atempo={remaining:.6f}")

    return filters if filters else ["atempo=1.0"]


def _build_rubberband_filter(speed_factor: float) -> str:
    """构建适合语音加速的 rubberband 参数。"""
    # 这些参数比 atempo 更适合语音类素材：
    # - formant=preserved: 保持人声共振峰，减少“变薄/发沙”
    # - smoothing=on + detector=soft: 减少颗粒感和毛刺
    # - channels=together: 保持多声道相位一致
    # - pitchq=quality: 选择高质量模式
    return (
        "rubberband="
        f"tempo={speed_factor:.6f}:"
        "transients=smooth:"
        "detector=soft:"
        "phase=laminar:"
        "window=standard:"
        "smoothing=on:"
        "formant=preserved:"
        "pitchq=quality:"
        "channels=together"
    )


def _select_ffmpeg_speed_backend(speed_factor: float) -> str:
    """为语音素材选择更稳妥的 ffmpeg 变速后端。

    经验规则：
    - 默认优先 atempo，语音自然度更好
    - 需要 rubberband 时可通过环境变量强制启用
    可用环境变量 VIDEOLINGO_AUDIO_SPEED_BACKEND 强制覆盖：
    auto | atempo | rubberband
    """
    forced = str(os.environ.get("VIDEOLINGO_AUDIO_SPEED_BACKEND", "auto")).strip().lower()
    if forced == "rubberband" and _ffmpeg_has_filter("rubberband"):
        return "rubberband"

    # auto 模式下默认使用 atempo（语音自然度更佳）
    return "atempo"


def _build_ffmpeg_speed_filter(speed_factor: float, backend: str = "auto") -> str:
    """构建 ffmpeg 变速滤镜串。"""
    chosen = backend
    if chosen == "auto":
        chosen = _select_ffmpeg_speed_backend(speed_factor)
    if chosen == "rubberband" and _ffmpeg_has_filter("rubberband"):
        return _build_rubberband_filter(speed_factor)
    return ",".join(_build_atempo_chain(speed_factor))


def _adjust_with_numpy(input_path: str, output_path: str, speed_factor: float) -> bool:
    """使用 numpy 线性插值重采样变速（会变调，仅保留给非关键路径使用）"""
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(input_path)
    original_len = len(data)

    # 线性插值重采样
    new_len = int(original_len / speed_factor)
    old_indices = np.arange(original_len)
    new_indices = np.linspace(0, original_len - 1, new_len)
    stretched = np.interp(new_indices, old_indices, data.astype(np.float64))

    # 确保数据类型与原文件一致
    if data.dtype == np.int16:
        stretched = np.clip(stretched, -32768, 32767).astype(np.int16)

    sf.write(output_path, stretched, sr, subtype='PCM_16')
    return True


def adjust_audio_speed_precise(
    input_path: str, output_path: str,
    speed_factor: float, target_duration: float = None,
) -> tuple:
    """变速不变音高，精确到采样点。

    优先使用 librosa / rubberband / ffmpeg atempo 等不变调方案。
    如果没有任何保真后端，则直接报错，避免静默降级到会变调方案。

    可选提供 target_duration 将输出裁剪/填充到精确采样数。

    Args:
        input_path: 输入音频文件路径
        output_path: 输出音频文件路径
        speed_factor: 变速倍数，>1.0 加速，<1.0 减速
        target_duration: 可选，精确目标时长（秒）

    Returns:
        (actual_duration_sec, sample_rate) 元组
    """
    import numpy as np
    import soundfile as sf

    # 读取原始音频
    data, sr = sf.read(input_path, dtype='float32')
    if data.ndim > 1:
        data = np.mean(data, axis=1)

    # 变速不变音高（优先 librosa / rubberband / ffmpeg）
    stretched = _time_stretch_pitch_preserve(data, sr, speed_factor, input_path=input_path)

    # 精确目标时长裁剪/填充
    if target_duration is not None and target_duration > 0:
        target_samples = int(round(target_duration * sr))
        if len(stretched) > target_samples:
            stretched = stretched[:target_samples]
        elif len(stretched) < target_samples:
            stretched = np.pad(stretched, (0, target_samples - len(stretched)))

    # 防溢出归一化
    max_val = np.max(np.abs(stretched))
    if max_val > 1.0:
        stretched = stretched / max_val

    out_ext = Path(output_path).suffix.lower()
    if out_ext == ".wav":
        sf.write(output_path, stretched.astype(np.float32), sr, subtype='PCM_24')
    elif out_ext == ".flac":
        sf.write(output_path, stretched.astype(np.float32), sr, format='FLAC')
    else:
        sf.write(output_path, stretched.astype(np.float32), sr)
    actual_duration = len(stretched) / sr
    return (actual_duration, sr)


def _time_stretch_pitch_preserve(
    data: "np.ndarray",
    sr: int,
    speed_factor: float,
    input_path: str = None,
) -> "np.ndarray":
    """变速不变音高，优先语音质量：rubberband → ffmpeg → librosa。"""
    import numpy as np

    if abs(speed_factor - 1.0) < 0.001:
        return data

    # 策略1: Python rubberband 包装
    try:
        import soundfile as sf
        import tempfile
        if _HAS_RUBBERBAND:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
                tmp_out_path = tmp_out.name
            try:
                source_path = input_path
                tmp_in_path = None
                if not source_path:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
                        tmp_in_path = tmp_in.name
                    sf.write(tmp_in_path, data, sr, subtype='PCM_24')
                    source_path = tmp_in_path
                if _adjust_with_rubberband(source_path, tmp_out_path, speed_factor):
                    stretched, _ = sf.read(tmp_out_path, dtype='float32')
                    _log_stretch_backend("python rubberband", speed_factor)
                    return stretched.astype(np.float32)
            finally:
                if tmp_in_path and os.path.exists(tmp_in_path):
                    os.unlink(tmp_in_path)
                if os.path.exists(tmp_out_path):
                    os.unlink(tmp_out_path)
    except Exception as e:
        logger.debug(f"python rubberband 变速失败，回退: {e}")

    # 策略2: ffmpeg rubberband/atempo
    try:
        import tempfile
        import soundfile as sf
        if _ffmpeg_available():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
                tmp_out_path = tmp_out.name
            try:
                ffmpeg_input = input_path
                tmp_in_path = None
                if not ffmpeg_input:
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
                        tmp_in_path = tmp_in.name
                    sf.write(tmp_in_path, data, sr, subtype='PCM_24')
                    ffmpeg_input = tmp_in_path
                success = _adjust_with_ffmpeg(ffmpeg_input, tmp_out_path, speed_factor)
                if success and os.path.exists(tmp_out_path):
                    stretched, _ = sf.read(tmp_out_path, dtype='float32')
                    _log_stretch_backend("ffmpeg", speed_factor)
                    return stretched.astype(np.float32)
            finally:
                if tmp_in_path and os.path.exists(tmp_in_path):
                    os.unlink(tmp_in_path)
                if os.path.exists(tmp_out_path):
                    os.unlink(tmp_out_path)
    except Exception as e:
        logger.debug(f"ffmpeg 变速失败，回退: {e}")

    # 策略3: rubberband CLI（变速不变音高）
    try:
        import subprocess
        import tempfile
        if shutil.which("rubberband"):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
                tmp_in_path = tmp_in.name
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_out:
                tmp_out_path = tmp_out.name
            import soundfile as sf
            sf.write(tmp_in_path, data, sr, subtype='PCM_24')
            cmd = [
                "rubberband", "--tempo", str(speed_factor),
                tmp_in_path, tmp_out_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode == 0 and os.path.exists(tmp_out_path):
                stretched, _ = sf.read(tmp_out_path, dtype='float32')
                os.unlink(tmp_in_path)
                os.unlink(tmp_out_path)
                return stretched.astype(np.float32)
            os.unlink(tmp_in_path)
            if os.path.exists(tmp_out_path):
                os.unlink(tmp_out_path)
    except Exception as e:
        logger.debug(f"rubberband CLI 变速失败，回退: {e}")

    # 策略4: librosa phase vocoder（变速不变音高）
    try:
        import librosa
        # librosa.effects.time_stretch 的 rate 参数：
        # rate > 1.0 加速，rate < 1.0 减速（与 speed_factor 含义一致）
        stretched = librosa.effects.time_stretch(data.astype(np.float64), rate=speed_factor)
        _log_stretch_backend("librosa phase vocoder（音质较低，可能出现沙沙声）", speed_factor)
        return stretched.astype(np.float32)
    except Exception as e:
        logger.debug(f"librosa time_stretch 失败，回退: {e}")

    raise RuntimeError(
        f"没有可用的不变调音频变速后端，speed_factor={speed_factor:.3f}"
    )


_STRETCH_BACKEND_LOGGED = set()


def _log_stretch_backend(backend: str, speed_factor: float) -> None:
    """首次使用某变速后端时打印一次诊断信息，便于排查音质问题。"""
    if backend in _STRETCH_BACKEND_LOGGED:
        return
    _STRETCH_BACKEND_LOGGED.add(backend)
    print(f"[audio_speed] 音频变速后端: {backend} (示例倍率 {speed_factor:.3f}x)")


def resample_audio(data: "np.ndarray", orig_sr: int, target_sr: int) -> "np.ndarray":
    """将音频数据从 orig_sr 重采样到 target_sr（带抗混叠滤波）。

    早期实现用 np.interp 线性插值，降采样时没有低通滤波，
    会把高频能量混叠回可听频段，产生“沙沙”的噪声底。
    现在优先使用 soxr，其次 scipy 多相滤波，均内置抗混叠滤波。
    """
    import numpy as np
    orig_sr = int(orig_sr)
    target_sr = int(target_sr)
    if orig_sr == target_sr:
        return data

    # 首选 soxr（高质量重采样，项目依赖中已包含）
    try:
        import soxr
        resampled = soxr.resample(data, orig_sr, target_sr, quality="HQ")
        return resampled.astype(np.float32, copy=False)
    except Exception as e:
        logger.debug(f"soxr 重采样失败，回退 scipy: {e}")

    # 其次 scipy 多相滤波重采样（自带抗混叠 FIR 滤波）
    try:
        from math import gcd
        from scipy.signal import resample_poly
        divisor = gcd(target_sr, orig_sr)
        resampled = resample_poly(data, target_sr // divisor, orig_sr // divisor)
        return resampled.astype(np.float32, copy=False)
    except Exception as e:
        logger.debug(f"scipy 重采样失败，回退线性插值: {e}")

    # 最后兜底：线性插值（无抗混叠，仅在依赖均不可用时使用）
    duration = len(data) / orig_sr
    target_len = int(round(duration * target_sr))
    old_indices = np.arange(len(data))
    new_indices = np.linspace(0, len(data) - 1, target_len)
    return np.interp(new_indices, old_indices, data).astype(np.float32)


def generate_silence(duration_sec: float, output_path: str, sample_rate: int = 44100) -> None:
    """生成指定时长的静音 WAV 文件"""
    import numpy as np
    import soundfile as sf

    num_samples = int(duration_sec * sample_rate)
    silence = np.zeros(num_samples, dtype=np.int16)
    sf.write(output_path, silence, sample_rate, subtype='PCM_16')
