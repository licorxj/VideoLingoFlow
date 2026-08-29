"""BS-Roformer separation engine: wraps bs-roformer-infer for vocal/background separation.

Uses the bs-roformer-infer package (bs_roformer namespace) which provides:
  - MODEL_REGISTRY: model discovery (10+ pretrained models)
  - download.download_model_assets(): auto-download checkpoints + configs
  - get_model_from_config(): instantiate model from YAML config
  - demix_track(): run inference on audio tensor
"""
import os
import gc
import shutil
import warnings
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
import soundfile as sf
import torch
import yaml
from ml_collections import ConfigDict

from backend.separation.sep_base import SeparationBase
from backend.separation.separation_interface_manager import get_separation_interface_manager


class BSRoformerSeparation(SeparationBase):
    """Vocal separation using BS-Roformer (Band-Split RoPE Transformer).

    Relies on the `bs-roformer-infer` package which bundles model architecture,
    pretrained checkpoints, config files, and automatic download.
    """

    def __init__(self, iface_id: str = "bs_roformer"):
        mgr = get_separation_interface_manager()
        iface = mgr.get(iface_id) or mgr.get("bs_roformer")
        self._config = (iface or {}).get("config", {})

    # ------------------------------------------------------------------
    # Cache directory (aligned with _model_cache)
    # ------------------------------------------------------------------

    @property
    def _model_cache(self) -> Path:
        """Return the project model cache directory for BS-Roformer assets."""
        base = os.environ.get(
            "HF_HOME",
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "_model_cache",
            ),
        )
        return Path(base) / "bs_roformer"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def separate(
        self,
        input_path: str,
        output_dir: str,
        callback: Optional[Callable] = None,
        *,
        model: str = "",
        format: str = "",
        **kwargs,
    ) -> dict:
        """Separate vocals from background using a BS-Roformer model.

        Parameters
        ----------
        input_path : str   Path to input audio file.
        output_dir : str   Directory to write separated audio files.
        callback : callable  (percent: int, message: str) progress callback.
        model : str  Model slug from the bs-roformer-infer registry.
        format : str  Output audio format ("wav" or "mp3").

        Returns
        -------
        dict  {"vocals": path, "background": path}
        """
        from bs_roformer import MODEL_REGISTRY, download
        from bs_roformer.inference import SafeLoaderWithTuple
        from bs_roformer import get_model_from_config

        if callback:
            callback(20, "Running BS-Roformer separation...")

        cfg = self._config
        use_model = model or cfg.get("model", "roformer-model-bs-roformer-sw-by-jarredou")
        fmt = format or cfg.get("format", "wav")

        # --- Resolve model entry from registry ---
        entry = MODEL_REGISTRY.get(use_model)
        if entry is None:
            raise ValueError(f"Unknown BS-Roformer model: {use_model}. "
                             f"Available: {[m.slug for m in MODEL_REGISTRY.list()]}")

        # A De-Reverb model only removes reverb from the input; it does NOT
        # separate vocals from background, which this node requires. Reject it
        # early with a clear message instead of failing later with a confusing
        # "incomplete artifacts" error.
        if getattr(entry, "category", "") == "dereverb":
            raise ValueError(
                f"模型 “{entry.name}” 是去混响(De-Reverb)模型，只输出去混响后的音频，"
                f"不会把人声与伴奏分离。人声分离节点需要能同时输出 vocals 与 "
                f"background（或 other/accompaniment）的模型，例如 "
                f"“BS Roformer | Vocals Revive V3e by Unwa”"
                f"（slug: roformer-model-bs-roformer-vocals-revive-v3e-by-unwa）。"
                f"请在节点配置的 model 中改选人声分离模型。"
            )

        model_cache = self._model_cache
        model_cache.mkdir(parents=True, exist_ok=True)

        # --- Step 1: Download model assets if not cached ---
        if callback:
            callback(22, f"Loading model: {entry.name}...")

        # Override stale base URLs with current mirrors from bs_modelsmap.json
        self._configure_download_urls(entry)

        try:
            download.download_model_assets([entry], model_cache)
        except Exception:
            # Retry with HuggingFace backup URLs
            print(f"[BS-Roformer] GitHub download failed, trying HF backup...", flush=True)
            self._configure_download_urls(entry, use_hf=True)
            try:
                download.download_model_assets([entry], model_cache)
            except Exception as e:
                print(f"[BS-Roformer] Model download failed: {e}", flush=True)
                if callback:
                    callback(24, f"Model download failed, falling back to FFmpeg...")
                return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)

        # --- Step 2: Load YAML config ---
        config_path = model_cache / entry.slug / entry.config
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")

        with open(config_path, "r") as f:
            config = ConfigDict(yaml.load(f, Loader=SafeLoaderWithTuple))

        # --- Step 3: Build model and load checkpoint ---
        if callback:
            callback(25, "Building model...")

        model = get_model_from_config("bs_roformer", config)
        checkpoint_path = model_cache / entry.slug / entry.checkpoint
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        state_dict = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        # Strip 'module.' prefix if present (from DataParallel saved checkpoints)
        if any(k.startswith("module.") for k in state_dict):
            state_dict = {k.removeprefix("module."): v for k, v in state_dict.items()}
        model.load_state_dict(state_dict, strict=False)
        del state_dict
        gc.collect()

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        model.eval()

        if callback:
            callback(30, f"Model loaded on {device}")

        # --- Step 4: Load input audio ---
        if callback:
            callback(35, "Loading audio...")
        mix, sr = sf.read(input_path, dtype="float32")
        if mix.ndim == 1:
            mix = mix[:, None]  # (samples,) -> (samples, 1)
        if mix.shape[1] > 2:
            mix = mix[:, :2]  # downmix to stereo

        # Keep a mono reference of the original input so we can derive a
        # background track (= input - vocals) for single-stem models that only
        # output a `vocals` stem (e.g. Vocals Revive V3e).
        raw_mix = mix.mean(axis=1, keepdims=True).astype(np.float32)  # (samples, 1)

        # BS-Roformer asserts that the input channel count matches its `stereo`
        # flag: a stereo-trained model (stereo=True) expects 2 channels, a mono
        # model expects 1. A mismatch raises an AssertionError and triggers the
        # FFmpeg fallback. Adapt the input to satisfy the model's expectation.
        want_stereo = bool(getattr(model, "stereo", False))
        if want_stereo and mix.shape[1] == 1:
            mix = np.repeat(mix, 2, axis=1)  # mono -> stereo
        elif not want_stereo and mix.shape[1] == 2:
            mix = mix.mean(axis=1, keepdims=True)  # stereo -> mono

        # demix_track has chunk-alignment issues with non-standard STFT configs
        # (hop_length != 512). Use direct model inference instead.
        mix_t = torch.from_numpy(mix.T).unsqueeze(0).to(device)  # (1, ch, samples)

        # --- Step 5: Run inference ---
        if callback:
            callback(40, "Running separation...")

        try:
            with torch.no_grad():
                with torch.cuda.amp.autocast():
                    raw_out = model(mix_t)

            # Normalize output array to (num_stems, channels, samples)
            raw_out = raw_out.cpu().numpy()
            # Model output shape depends on num_stems:
            #   num_stems=1: (batch, ch, samples) -> 3D
            #   num_stems>1: (batch, stems, ch, samples) -> 4D
            if raw_out.ndim == 4 and raw_out.shape[0] == 1:
                raw_out = raw_out[0, :, :, :]  # (stems, ch, samples)

            instruments = list(config.training.get("instruments", ["vocals"]))
            num_stems = raw_out.shape[0]

            sources_dict = {}
            for i in range(num_stems):
                stem_name = instruments[i] if i < len(instruments) else f"stem_{i}"
                src = raw_out[i].T  # (ch, samples) -> (samples, ch)
                # Downmix to mono so downstream steps (which expect mono) behave
                # consistently, even when a stereo-trained model emitted 2 channels.
                if src.shape[1] > 1:
                    src = src.mean(axis=1, keepdims=True)
                sources_dict[stem_name] = src

        except Exception as e:
            print(f"[BS-Roformer] Inference failed: {e}", flush=True)
            if callback:
                callback(24, f"Inference failed, falling back to FFmpeg...")
            return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)

        # Clean up GPU memory
        del model, mix_t
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        if callback:
            callback(70, "Writing output files...")

        # --- Step 6: Write output ---
        roformer_out = os.path.join(output_dir, "bs_roformer_output")
        os.makedirs(roformer_out, exist_ok=True)

        # Save ALL individual stems (if multi-stem model)
        for src_name, src_data in sources_dict.items():
            stem_path = os.path.join(roformer_out, f"{src_name}.wav")
            data_2d = np.asarray(src_data, dtype=np.float32)
            if data_2d.ndim == 1:
                data_2d = data_2d[:, None]
            sf.write(stem_path, data_2d, int(sr))

        # Build vocals + background (pipeline contract)
        vocals_key = self._find_vocals_key(sources_dict)
        bg_key = self._find_background_key(sources_dict)

        vocals_path = os.path.join(roformer_out, f"{vocals_key or 'vocals'}.wav")
        bg_path = os.path.join(roformer_out, f"{bg_key or 'background'}.wav") if bg_key else None

        if not vocals_key:
            if callback:
                callback(24, "No vocals output from model, falling back to FFmpeg...")
            return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)

        # Mix non-vocals into background if no explicit background stem
        if not bg_key:
            bg_audio = None
            for src_name, src_data in sources_dict.items():
                if src_name != vocals_key:
                    bg_audio = (src_data.copy() if bg_audio is None else bg_audio + src_data)
            if bg_audio is None:
                # Single-stem model (only vocals): derive background = input - vocals
                vocals_data = sources_dict.get(vocals_key)
                if vocals_data is not None and raw_mix is not None:
                    n = min(raw_mix.shape[0], vocals_data.shape[0])
                    bg_audio = raw_mix[:n] - vocals_data[:n]
                if bg_audio is not None:
                    bg_path = os.path.join(roformer_out, "background.wav")
                    sf.write(bg_path, np.asarray(bg_audio, dtype=np.float32).T, sr)
                else:
                    bg_path = None

        if callback:
            callback(80, "Moving output files...")

        vocals_dst = os.path.join(output_dir, f"vocals.{fmt}")
        bg_dst = os.path.join(output_dir, f"background.{fmt}")

        if os.path.exists(vocals_path):
            self._convert_and_move(vocals_path, vocals_dst)
        if bg_path and os.path.exists(bg_path):
            self._convert_and_move(bg_path, bg_dst)

        stem_names = list(sources_dict.keys())
        print(f"[BS-Roformer] Stems available: {stem_names}", flush=True)
        print(f"[BS-Roformer] All stems saved to: {roformer_out}", flush=True)

        if not os.path.exists(vocals_dst):
            raise Exception(f"Vocals output not found: {vocals_dst}")

        result = {"vocals": vocals_dst}
        if os.path.exists(bg_dst):
            result["background"] = bg_dst

        if callback:
            callback(100, "BS-Roformer separation completed")

        return result

    # ------------------------------------------------------------------
    # Model download URL management
    # ------------------------------------------------------------------

    def _configure_download_urls(self, entry, use_hf: bool = False):
        """Override stale download URLs with current mirrors from bs_modelsmap.json.

        The original bs-roformer-infer package points to TRvlvr's GitHub releases
        which have expired.  This method reads the local model map file and
        sets the download module's base URLs / overrides accordingly.

        Two sources (GitHub primary, HuggingFace backup) are available for every
        model.  When *use_hf* is False, the primary GitHub URL is used; when True,
        the HF mirror is used.
        """
        import json as _json
        from bs_roformer import download as _dl

        map_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "bs_modelsmap.json"
        )
        if not os.path.exists(map_path):
            return  # no map file, keep defaults (will likely fail)

        with open(map_path, "r", encoding="utf-8") as f:
            model_map = _json.load(f)

        # Try to find the matching entry in the map by checkpoint filename
        matched_key = None
        for key, val in model_map.items():
            gh_urls = val.get("Github", [])
            hf_urls = val.get("HuggingFace", [])
            all_urls = gh_urls + hf_urls
            if any(entry.checkpoint in u for u in all_urls):
                matched_key = key
                break

        if matched_key is None:
            return

        gh = model_map[matched_key].get("Github", [])
        hf = model_map[matched_key].get("HuggingFace", [])

        if use_hf and hf:
            # Set per-file overrides using HF URLs
            self._set_url_overrides(entry, hf)
            _dl.DEFAULT_CKPT_BASE_URL = "https://huggingface.co/Eddycrack864/audio-separator-models/resolve/main/roformers/"
            _dl.DEFAULT_CONFIG_BASE_URL = "https://huggingface.co/Eddycrack864/audio-separator-models/resolve/main/roformers/"
        elif gh:
            # Set per-file overrides using GitHub URLs
            self._set_url_overrides(entry, gh)
            _dl.DEFAULT_CKPT_BASE_URL = "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/"
            _dl.DEFAULT_CONFIG_BASE_URL = "https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/"

    @staticmethod
    def _set_url_overrides(entry, urls: list):
        """Set per-file CHECKPOINT_URL_OVERRIDES / CONFIG_URL_OVERRIDES.

        *urls* is a list of 1-2 entries from the model map:
          [checkpoint_url, config_url]
        """
        from bs_roformer import download as _dl

        if len(urls) >= 1 and entry.checkpoint:
            _dl.CHECKPOINT_URL_OVERRIDES[entry.checkpoint] = urls[0]
            # Also add to STATIC_CHECKPOINT_OVERRIDES for persistence
            _dl.STATIC_CHECKPOINT_OVERRIDES[entry.checkpoint] = urls[0]
        if len(urls) >= 2 and entry.config:
            _dl.CONFIG_URL_OVERRIDES[entry.config] = urls[1]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _find_vocals_key(sources: dict) -> Optional[str]:
        """Find the vocals key in the sources dict."""
        # Common names for vocals stem
        for key in ("vocals", "vocals", "voice", "vocal"):
            if key in sources:
                return key
        # Fallback: first key (for single-stem models)
        if len(sources) == 1:
            return next(iter(sources.keys()))
        return None

    @staticmethod
    def _find_background_key(sources: dict) -> Optional[str]:
        """Find the background/instrumental key in the sources dict."""
        for key in ("other", "accompaniment", "instrumental", "no_vocals", "background", "no_vocal"):
            if key in sources:
                return key
        return None

    def _convert_and_move(self, src: str, dst: str):
        """Convert audio format if needed using ffmpeg, otherwise copy."""
        if not os.path.exists(src):
            raise Exception(f"Source file not found: {src}")
        src_ext = os.path.splitext(src)[1].lower().lstrip(".")
        dst_ext = os.path.splitext(dst)[1].lower().lstrip(".")
        if src_ext == dst_ext:
            shutil.copy2(src, dst)
        else:
            import subprocess
            cmd = [
                "ffmpeg", "-y", "-i", src,
                "-acodec", "pcm_s16le" if dst_ext == "wav" else "libmp3lame",
                dst,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise Exception(f"Audio conversion failed: {result.stderr[:300]}")

    def _run_ffmpeg_fallback(self, audio_path: str, output_dir: str, fmt: str, callback=None):
        """Emergency fallback using FFmpeg center/side extraction."""
        import subprocess
        if callback:
            callback(30, "Running FFmpeg fallback separation...")

        vocals_dst = os.path.join(output_dir, f"vocals.{fmt}")
        bg_dst = os.path.join(output_dir, f"background.{fmt}")
        codec = "pcm_s16le" if fmt == "wav" else "libmp3lame"

        vocals_cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-af", "pan=stereo|FL=0.5*FL+0.5*FR|FR=0.5*FL+0.5*FR,highpass=f=120,lowpass=f=7000",
            "-acodec", codec, vocals_dst,
        ]
        bg_cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-af", "pan=stereo|FL=0.5*FL-0.5*FR|FR=0.5*FR-0.5*FL",
            "-acodec", codec, bg_dst,
        ]

        vocals_res = subprocess.run(vocals_cmd, capture_output=True, text=True, timeout=600)
        if vocals_res.returncode != 0:
            raise Exception(f"FFmpeg fallback vocals failed: {vocals_res.stderr[:500]}")

        bg_res = subprocess.run(bg_cmd, capture_output=True, text=True, timeout=600)
        if bg_res.returncode != 0:
            raise Exception(f"FFmpeg fallback background failed: {bg_res.stderr[:500]}")

        return {"vocals": vocals_dst, "background": bg_dst}
