"""sherpa-onnx 语音降噪（GTCRN / DPDFNet）。

作为"声音降噪"节点的可选引擎：比 FFmpeg 的 afftdn 频域降噪更能保人声，
且模型极小（GTCRN 0.5MB、DPDFNet 8~14MB），无需 torch。

用法：
    denoise_audio_file(input_path, output_path, model="gtcrn_simple")
输出为 wav（调用方如需 mp3/flac 再自行转码）。
"""
import os
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

from backend.asr import sherpa_models

DEFAULT_MODEL = sherpa_models.DEFAULT_DENOISE_MODEL


def _import_sherpa():
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise RuntimeError(
            f"sherpa-onnx 未安装，无法使用 sherpa 降噪（pip install sherpa-onnx）：{exc}"
        ) from exc
    return sherpa_onnx


def _read_mono(path: str, target_sr: int):
    """任意音源 -> (float32 mono samples, 采样率)。统一经 ffmpeg 转目标采样率。"""
    import numpy as np
    import soundfile as sf
    from backend.utils.ffmpeg_guard import apply_resource_args

    tmp_dir = tempfile.mkdtemp(prefix="sherpa_denoise_")
    wav = os.path.join(tmp_dir, "in.wav")
    try:
        cmd = apply_resource_args([
            "ffmpeg", "-y", "-i", path, "-vn", "-ac", "1", "-ar", str(target_sr),
            "-c:a", "pcm_s16le", wav,
        ])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0 or not os.path.exists(wav):
            raise RuntimeError(f"ffmpeg 读取音频失败: {proc.stderr[-400:]}")
        data, sr = sf.read(wav, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        return np.ascontiguousarray(data, dtype="float32"), sr
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def denoise_audio_file(
    input_path: str,
    output_path: str,
    *,
    model: str = DEFAULT_MODEL,
    num_threads: int = 2,
    provider: str = "cpu",
    attenuation_limit_db: float = 0.0,
    callback: Optional[Callable] = None,
    progress_range: tuple = (0, 100),
) -> str:
    """对音频文件做语音降噪，写出 wav，返回输出路径。"""
    sherpa_onnx = _import_sherpa()

    def _cb(pct, msg):
        if callback:
            try:
                callback(int(pct), msg)
            except Exception:
                pass

    lo, hi = progress_range
    _cb(lo, f"准备 sherpa 降噪模型 {model} ...")
    info = sherpa_models.ensure_denoise_model(
        model, callback=callback,
        progress_range=(lo, lo + (hi - lo) * 0.5))

    model_cfg = sherpa_onnx.OfflineSpeechDenoiserModelConfig(
        num_threads=max(1, int(num_threads)),
        provider=provider,
    )
    if info["kind"] == "dpdfnet":
        model_cfg.dpdfnet = sherpa_onnx.OfflineSpeechDenoiserDpdfNetModelConfig(
            model=info["path"], attenuation_limit_db=float(attenuation_limit_db))
    else:
        model_cfg.gtcrn = sherpa_onnx.OfflineSpeechDenoiserGtcrnModelConfig(
            model=info["path"])

    denoiser = sherpa_onnx.OfflineSpeechDenoiser(
        sherpa_onnx.OfflineSpeechDenoiserConfig(model=model_cfg))

    target_sr = int(denoiser.sample_rate or 16000)
    _cb(lo + (hi - lo) * 0.6, f"读取音频并重采样到 {target_sr}Hz ...")
    samples, sr = _read_mono(input_path, target_sr)

    _cb(lo + (hi - lo) * 0.7, "执行降噪 ...")
    denoised = denoiser.run(samples, sr)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    import soundfile as sf
    sf.write(output_path, denoised.samples, int(denoised.sample_rate or target_sr))
    _cb(hi, f"降噪完成 -> {os.path.basename(output_path)}")
    return output_path
