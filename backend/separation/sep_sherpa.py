"""sherpa-onnx 音源分离引擎（Spleeter 2stems，人声 / 伴奏）。

零 torch 依赖：onnxruntime 推理，模型仅约 46MB（int8 双模型，自动下载）。
实测调用约定（与官方示例一致）：
  * 输入 samples 形状必须为 (num_channels, num_samples) 的 float32，采样率 44100
  * `process(sample_rate, samples)` 返回 OfflineSourceSeparationOutput
  * `output.stems[0]` = vocals、`output.stems[1]` = 伴奏，元素为 MultiChannelSamples（`.data` 为 ndarray）
"""
import os
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

from backend.asr import sherpa_models
from backend.separation.sep_base import SeparationBase

SAMPLE_RATE = 44100


class SherpaSpleeterSeparation(SeparationBase):
    """sherpa-onnx Spleeter 2stems 分离引擎。"""

    def __init__(self, **kwargs):
        self.options = kwargs or {}

    # ------------------------------------------------------------------
    def _load_stereo(self, input_path: str) -> tuple:
        """任意音源 -> (float32 ndarray (ch, n), sample_rate=44100)。"""
        import numpy as np
        import soundfile as sf
        from backend.utils.ffmpeg_guard import apply_resource_args

        tmp_dir = tempfile.mkdtemp(prefix="sherpa_sep_")
        wav = os.path.join(tmp_dir, "in44k.wav")
        cmd = apply_resource_args([
            "ffmpeg", "-y", "-i", input_path, "-vn",
            "-ac", "2", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", wav,
        ])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0 or not os.path.exists(wav):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(f"ffmpeg 提取音频失败: {proc.stderr[-400:]}")

        data, sr = sf.read(wav, dtype="float32", always_2d=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        # (num_samples, num_channels) -> (num_channels, num_samples)
        return np.ascontiguousarray(data.T), sr

    @staticmethod
    def _write_stem(path: str, channels_first, sample_rate: int) -> str:
        import numpy as np
        import soundfile as sf
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = np.asarray(channels_first, dtype="float32")
        if data.ndim == 2:
            data = data.T  # -> (num_samples, num_channels)
        sf.write(path, data, int(sample_rate))
        return path

    @staticmethod
    def _transcode(src: str, dst: str, fmt: str) -> None:
        from backend.utils.ffmpeg_guard import apply_resource_args
        encode = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
                  "flac": ["-c:a", "flac"]}.get(fmt, ["-acodec", "pcm_s16le"])
        cmd = apply_resource_args(["ffmpeg", "-y", "-i", src, *encode, dst])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"转码失败 ({fmt}): {proc.stderr[-300:]}")

    # ------------------------------------------------------------------
    def separate(self, input_path: str, output_dir: str,
                 callback: Optional[Callable] = None, **kwargs) -> dict:
        """人声/伴奏分离，返回 {"vocals": <path>, "background": <path>}。"""
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                f"sherpa-onnx 未安装，无法使用 sherpa 分离（pip install sherpa-onnx）：{exc}"
            ) from exc

        def _cb(pct, msg):
            if callback:
                try:
                    callback(int(pct), msg)
                except Exception:
                    pass

        model = str(kwargs.get("model") or sherpa_models.DEFAULT_SEPARATION_MODEL).strip()
        fmt = str(kwargs.get("format") or "wav").strip().lower()
        num_threads = int(kwargs.get("num_threads") or 2)
        provider = str(kwargs.get("provider") or "cpu")

        _cb(5, "准备 sherpa Spleeter 模型 ...")
        info = sherpa_models.ensure_separation_model(
            model, callback=callback, progress_range=(5, 45))

        _cb(50, "构建分离器 ...")
        config = sherpa_onnx.OfflineSourceSeparationConfig(
            model=sherpa_onnx.OfflineSourceSeparationModelConfig(
                spleeter=sherpa_onnx.OfflineSourceSeparationSpleeterModelConfig(
                    vocals=info["vocals"],
                    accompaniment=info["accompaniment"],
                ),
                num_threads=max(1, num_threads),
                provider=provider,
            )
        )
        separator = sherpa_onnx.OfflineSourceSeparation(config)

        _cb(55, "读取音频（重采样 44.1kHz 立体声）...")
        samples, sr = self._load_stereo(input_path)

        _cb(60, "执行人声/伴奏分离（耗时与音频时长成正比）...")
        output = separator.process(sample_rate=sr, samples=samples)

        stems = list(getattr(output, "stems", []) or [])
        if len(stems) < 2:
            raise RuntimeError(f"分离输出异常：stems={len(stems)}")

        os.makedirs(output_dir, exist_ok=True)
        out_rate = int(getattr(output, "sample_rate", SAMPLE_RATE) or SAMPLE_RATE)
        vocals_path = os.path.join(output_dir, "vocals.wav")
        bg_path = os.path.join(output_dir, "background.wav")

        _cb(90, "写出分离结果 ...")
        self._write_stem(vocals_path, stems[0].data, out_rate)
        self._write_stem(bg_path, stems[1].data, out_rate)

        if fmt and fmt != "wav":
            vocals_final = os.path.join(output_dir, f"vocals.{fmt}")
            bg_final = os.path.join(output_dir, f"background.{fmt}")
            self._transcode(vocals_path, vocals_final, fmt)
            self._transcode(bg_path, bg_final, fmt)
            os.remove(vocals_path)
            os.remove(bg_path)
            vocals_path, bg_path = vocals_final, bg_final

        _cb(100, "分离完成")
        return {"vocals": vocals_path, "background": bg_path}
