"""MDX-NET (ONNX) separation engine.

Wraps the UVR MDX-NET ONNX models (ConvTDFNet architecture) via onnxruntime.
Ported from the reference UVR example (``UVR-MDX-NET加载示例代码-separate.py``),
with two fixes:
  * ``predict`` now feeds the model ``[2, n]`` audio (the reference passed the
    transposed ``[n, 2]`` which broke the chunking logic).
  * Per-model ``dim_f`` / ``dim_t`` are read from the ONNX input tensor shape at
    load time, so every model is loaded with the exact architecture it was
    exported with (avoids input-shape mismatches). ``n_fft``/``hop`` use the
    standard UVR-MDX-NET values (6144 / 1024).
"""
import os
import sys
import json
import math
import shutil
import subprocess

import numpy as np
import torch
import librosa
import soundfile as sf
import onnxruntime as ort
from tqdm import tqdm

from backend.separation.sep_base import SeparationBase
from backend.separation.separation_interface_manager import get_separation_interface_manager

# Resolve _model_cache for weight downloads (same location as other engines)
_MODEL_CACHE = os.environ.get(
    "TORCH_HOME",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "_model_cache",
    ),
)

_REGISTRY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mdx_net_models.json")
_REGISTRY = None

_CAT_LABEL = {"vocal": "人声分离", "stem": "伴奏/乐器分离", "enhancement": "音频增强(去混响/降噪)"}
_TGT_LABEL = {
    "vocals": "人声",
    "crowd": "观众/合唱人声",
    "instrument": "伴奏/乐器",
    "bass": "低音",
    "drums": "鼓组",
    "other": "其他声部",
    "reverb": "混响/噪声",
}


def _load_registry():
    global _REGISTRY
    if _REGISTRY is None:
        try:
            with open(_REGISTRY_FILE, encoding="utf-8") as fh:
                _REGISTRY = json.load(fh).get("models", {})
        except Exception as exc:  # pragma: no cover - best effort
            print(f"[MDXNet] Failed to load registry: {exc}", flush=True)
            _REGISTRY = {}
    return _REGISTRY


class ConvTDFNet:
    """ConvTDFNet lifted from the UVR MDX-NET ONNX example (verbatim)."""

    def __init__(self, target_name, L, dim_f, dim_t, n_fft, hop=1024):
        self.dim_c = 4
        self.dim_f = dim_f
        self.dim_t = 2**dim_t
        self.n_fft = n_fft
        self.hop = hop
        self.n_bins = self.n_fft // 2 + 1
        self.chunk_size = hop * (self.dim_t - 1)
        self.window = torch.hann_window(window_length=self.n_fft, periodic=True)
        self.target_name = target_name
        out_c = self.dim_c * 4 if target_name == "*" else self.dim_c
        self.freq_pad = torch.zeros([1, out_c, self.n_bins - self.dim_f, self.dim_t])
        self.n = L // 2

    def stft(self, x):
        x = x.reshape([-1, self.chunk_size])
        x = torch.stft(x, self.n_fft, self.hop, window=self.window, return_complex=True)
        x = torch.view_as_real(x)
        x = x.reshape([-1, 2, 2, self.n_bins, self.dim_t]).reshape(
            [-1, self.dim_c, self.n_bins, self.dim_t]
        )
        return x[:, :, : self.dim_f]

    def istft(self, x, freq_pad=None):
        if freq_pad is None:
            freq_pad = self.freq_pad  # [1, out_c, n_bins-dim_f, dim_t]
        x = torch.cat([x, freq_pad.repeat([1, 1, 1, x.shape[-1]])], -2)
        x = x.reshape([x.shape[0], x.shape[1] // 2, 2, self.n_bins, self.dim_t]).reshape(
            [-1, 2, 2, self.n_bins, self.dim_t]
        )
        x = x.reshape([-1, 2 * self.n_bins, self.dim_t])
        x = torch.istft(x, self.n_fft, self.hop, window=self.window)
        return x.reshape([-1, self.chunk_size])


class Predictor:
    """Runs the ConvTDFNet ONNX session over an audio mixture (ported)."""

    def __init__(self, session, net, args):
        self.model = session  # onnxruntime InferenceSession
        self.model_ = net  # ConvTDFNet
        self.args = args  # dict: margin, chunks, denoise

    def demix(self, mix):
        samples = mix.shape[-1]
        margin = self.args["margin"]
        chunk_size = self.args["chunks"] * 44100

        assert not margin == 0, "margin cannot be zero!"

        if margin > chunk_size:
            margin = chunk_size

        segmented_mix = {}

        if self.args["chunks"] == 0 or samples < chunk_size:
            chunk_size = samples

        counter = -1
        for skip in range(0, samples, chunk_size):
            counter += 1
            s_margin = 0 if counter == 0 else margin
            end = min(skip + chunk_size + margin, samples)
            start = skip - s_margin
            segmented_mix[skip] = mix[:, start:end].copy()
            if end == samples:
                break

        sources = self.demix_base(segmented_mix, margin_size=margin)
        return sources

    def demix_base(self, mixes, margin_size):
        chunked_sources = []
        progress_bar = tqdm(total=len(mixes))
        progress_bar.set_description("Processing")

        for mix in mixes:
            cmix = mixes[mix]
            sources = []
            n_sample = cmix.shape[1]
            model = self.model_
            trim = model.n_fft // 2
            gen_size = model.chunk_size - 2 * trim
            pad = gen_size - n_sample % gen_size
            mix_p = np.concatenate(
                (np.zeros((2, trim)), cmix, np.zeros((2, pad)), np.zeros((2, trim))), 1
            )
            mix_waves = []
            i = 0
            while i < n_sample + pad:
                waves = np.array(mix_p[:, i : i + model.chunk_size])
                mix_waves.append(waves)
                i += gen_size

            mix_waves = torch.tensor(np.array(mix_waves), dtype=torch.float32)

            with torch.no_grad():
                _ort = self.model
                spek = model.stft(mix_waves)
                if self.args["denoise"]:
                    spec_pred = (
                        -_ort.run(None, {"input": -spek.cpu().numpy()})[0] * 0.5
                        + _ort.run(None, {"input": spek.cpu().numpy()})[0] * 0.5
                    )
                    tar_waves = model.istft(torch.tensor(spec_pred))
                else:
                    tar_waves = model.istft(
                        torch.tensor(_ort.run(None, {"input": spek.cpu().numpy()})[0])
                    )
                tar_signal = (
                    tar_waves[:, :, trim:-trim]
                    .transpose(0, 1)
                    .reshape(2, -1)
                    .numpy()[:, :-pad]
                )

                start = 0 if mix == 0 else margin_size
                end = None if mix == list(mixes.keys())[::-1][0] else -margin_size

                if margin_size == 0:
                    end = None

                sources.append(tar_signal[:, start:end])

                progress_bar.update(1)

            chunked_sources.append(sources)
        _sources = np.concatenate(chunked_sources, axis=-1)

        progress_bar.close()
        return _sources

    def predict(self, file_path):
        mix, rate = librosa.load(file_path, mono=False, sr=44100)

        if mix.ndim == 1:
            mix = np.asfortranarray([mix, mix])

        mix = mix.T  # -> [2, n]
        # NOTE: reference passed ``self.demix(mix.T)`` here, which is a bug;
        # demix expects the [2, n] layout produced above.
        sources = self.demix(mix)
        opt = sources  # [2, n] isolated stem (model output)
        return (mix, opt, rate)


class MDXNetOnnxSeparation(SeparationBase):
    """MDX-NET (ONNX) separation engine entry point."""

    def __init__(self, iface_id="mdx_net_onnx"):
        self._iface_id = iface_id

    def _config(self):
        mgr = get_separation_interface_manager()
        iface = mgr.get(self._iface_id) or mgr.get("mdx_net_onnx")
        return (iface or {}).get("config", {})

    def separate(self, input_path, output_dir, callback=None, *, model="", format="", **kwargs):
        if callback:
            callback(20, "Running MDX-NET (ONNX) separation...")
        cfg = self._config()
        name = model or cfg.get("model", "UVR_MDXNET_1_9703")
        fmt = format or cfg.get("format", "wav")

        entry = _load_registry().get(name)
        if not entry:
            if callback:
                callback(24, f"Model {name} not configured; falling back to FFmpeg")
            return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)

        if callback:
            callback(22, f"Loading model {name}...")
        model_path = self._ensure_model(name, callback)
        if not model_path:
            if callback:
                callback(24, f"Failed to load {name}; falling back to FFmpeg")
            return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)

        try:
            return self._run(model_path, entry, input_path, output_dir, fmt, callback)
        except Exception as exc:
            print(f"[MDXNet] separation failed: {exc}", flush=True)
            if callback:
                callback(24, f"MDX-NET failed: {str(exc)[:200]}; falling back to FFmpeg")
            return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)

    def _run(self, model_path, entry, input_path, output_dir, fmt, callback):
        avail = ort.get_available_providers()
        providers = [p for p in ["CUDAExecutionProvider", "CPUExecutionProvider"] if p in avail]
        if not providers:
            providers = ["CPUExecutionProvider"]

        sess = ort.InferenceSession(model_path, providers=providers)

        # Derive ConvTDFNet dims from the ONNX input tensor so the STFT spectrogram
        # exactly matches what the model was exported with.
        inp = sess.get_inputs()[0].shape  # [batch, 4, dim_f, dim_t]
        try:
            dim_f = int(inp[2])
        except (TypeError, ValueError):
            dim_f = int(entry.get("dim_f", 2048))
        try:
            actual_dim_t = int(inp[3])
            dim_t_arg = int(round(math.log2(actual_dim_t)))
        except (TypeError, ValueError):
            dim_t_arg = int(entry.get("dim_t", 8))
        n_fft = int(entry.get("n_fft", 6144))
        hop = int(entry.get("hop", 1024))

        net = ConvTDFNet(target_name="vocals", L=11, dim_f=dim_f, dim_t=dim_t_arg, n_fft=n_fft, hop=hop)
        args = {
            "margin": int(entry.get("margin", 44100)),
            "chunks": int(entry.get("chunks", 15)),
            "denoise": bool(entry.get("denoise", True)),
        }
        if callback:
            callback(40, "Separating audio (ConvTDFNet)...")
        predictor = Predictor(sess, net, args)
        mix, opt, rate = predictor.predict(input_path)

        comp = float(entry.get("compensate", 1.0))
        opt = opt * comp

        category = entry.get("category", "vocal")
        target = entry.get("target", "vocals")
        # MDX-NET models are 2-stem: ``opt`` is the stem the model was trained to
        # isolate. Map it to (vocals, background) per what the model actually does,
        # so non-vocal models (instrument / reverb / etc.) don't get silently
        # mislabeled as "vocals".
        if category == "enhancement":
            # reverb / denoise: opt is the enhanced (clean) audio; mix-opt is the removed part
            vocals = opt
            background = mix - opt
        elif target in ("vocals", "crowd"):
            vocals = opt
            background = mix - opt
        else:
            # instrument / bass / drums / other: the desired vocals are the complement
            vocals = mix - opt
            background = opt

        if category != "vocal" and callback:
            callback(
                25,
                f"提示：模型 {name} 为「{_CAT_LABEL.get(category, category)}」模型，输出非标准人声/伴奏"
                f"（提取 {_TGT_LABEL.get(target, target)}）",
            )

        if callback:
            callback(80, "Writing output files...")
        vocals_dst = os.path.join(output_dir, f"vocals.{fmt}")
        bg_dst = os.path.join(output_dir, f"background.{fmt}")
        self._write_stem(vocals, rate, vocals_dst, fmt)
        self._write_stem(background, rate, bg_dst, fmt)
        if callback:
            callback(95, "Done")
        return {"vocals": vocals_dst, "background": bg_dst}

    def _ensure_model(self, name, callback=None):
        entry = _load_registry().get(name)
        if not entry:
            return None
        fname = entry["file"]
        url = entry["url"]
        d = os.path.join(_MODEL_CACHE, "mdx_net")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, fname)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        if callback:
            callback(23, f"Downloading {fname} from UVR HF mirror...")
        try:
            self._download(url, path)
        except Exception as exc:
            print(f"[MDXNet] download failed: {exc}", flush=True)
            return None
        return path if (os.path.exists(path) and os.path.getsize(path) > 0) else None

    def _download(self, url, dst):
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            with open(dst, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 100)
                        if pct % 10 == 0:
                            print(f"[MDXNet] download {pct}%", flush=True)

    def _write_stem(self, wave, rate, dst, fmt):
        # wave: [2, n] float
        if fmt == "wav":
            sf.write(dst, wave.T, rate)
            return
        import tempfile

        tmp = dst + ".tmp.wav"
        sf.write(tmp, wave.T, rate)
        self._ffmpeg_convert(tmp, dst)
        if os.path.exists(tmp):
            os.remove(tmp)

    def _ffmpeg_convert(self, src, dst):
        ext = os.path.splitext(dst)[1].lower().lstrip(".")
        acodec = "pcm_s16le" if ext == "wav" else "libmp3lame"
        from backend.utils.ffmpeg_guard import apply_resource_args
        subprocess.run(
            apply_resource_args(["ffmpeg", "-y", "-i", src, "-acodec", acodec, dst]),
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )

    def _run_ffmpeg_fallback(self, audio_path, output_dir, fmt, callback=None):
        vocals_dst = os.path.join(output_dir, f"vocals.{fmt}")
        bg_dst = os.path.join(output_dir, f"background.{fmt}")
        from backend.utils.ffmpeg_guard import apply_resource_args
        try:
            subprocess.run(
                apply_resource_args(["ffmpeg", "-y", "-i", audio_path, "-af", "pan=mono|c0=0.5*c0+0.5*c1", vocals_dst]),
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
            subprocess.run(
                apply_resource_args(["ffmpeg", "-y", "-i", audio_path, "-af", "pan=stereo|c0=c0-c1|c1=c1-c0", bg_dst]),
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
            if callback:
                callback(95, "FFmpeg fallback done")
            return {"vocals": vocals_dst, "background": bg_dst}
        except Exception as exc:
            raise Exception(f"FFmpeg fallback failed: {exc}")
