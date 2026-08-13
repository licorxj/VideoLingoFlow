"""Demucs separation engine: wraps the demucs CLI for vocal/background separation."""
import os
import sys
import shutil
import subprocess
from typing import Callable, Optional

from backend.separation.sep_base import SeparationBase
from backend.separation.separation_interface_manager import get_separation_interface_manager

# Resolve _model_cache for torch.hub model downloads
_MODEL_CACHE = os.environ.get(
    "TORCH_HOME",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "_model_cache",
    ),
)


class DemucsSeparation(SeparationBase):
    """Vocal separation using Demucs CLI (htdemucs / mdx models)."""

    def __init__(self, iface_id: str = "demucs"):
        mgr = get_separation_interface_manager()
        iface = mgr.get(iface_id) or mgr.get("demucs")
        self._config = (iface or {}).get("config", {})

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
        if callback:
            callback(20, "Running Demucs separation...")

        cfg = self._config
        use_model = model or cfg.get("model", "htdemucs_ft")
        segment = cfg.get("segment", 1200)
        two_stems = cfg.get("two_stems", "vocals")
        fmt = format or cfg.get("format", "wav")
        timeout = cfg.get("timeout", 1800)

        # Probe demucs runtime availability
        probe = self._probe_demucs_runtime()
        if callback:
            callback(22, probe["message"])
        if not probe["ok"]:
            if callback:
                callback(24, "Demucs unavailable, falling back to FFmpeg separation...")
            return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)

        demucs_out = os.path.join(output_dir, "demucs_output")
        os.makedirs(demucs_out, exist_ok=True)

        # -- Preload model to _model_cache so the CLI doesn't need to download --
        if callback:
            callback(23, f"Loading model {use_model}...")
        model_info = self._ensure_model(use_model)
        if not model_info:
            if callback:
                callback(24, f"Failed to load model {use_model}, falling back to FFmpeg...")
            return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)

        model_name, max_segment = model_info
        # Cap segment to model's maximum (Transformer models have hard limits)
        if max_segment is not None and segment > max_segment:
            capped = int(max_segment)
            print(f"[Demucs] Segment capped: {segment}s -> {capped}s (model max: {max_segment:.1f}s)", flush=True)
            if callback:
                callback(23, f"Segment auto-adjusted: {segment}s -> {capped}s")
            segment = capped
        elif max_segment is None and segment > 10:
            # htdemucs_ft etc. have a hidden segment limit ~7.8s even without exposing .segment
            capped = 7
            print(f"[Demucs] Segment capped (no model attr): {segment}s -> {capped}s", flush=True)
            if callback:
                callback(23, f"Segment auto-adjusted for safety: {segment}s -> {capped}s")
            segment = capped

        cmd = [
            "demucs",
            "--two-stems", two_stems,
            "--segment", str(segment),
            "-n", model_name,
            "-o", demucs_out,
            input_path,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, cwd=output_dir
            )
            if result.returncode != 0:
                detail = (
                    f"Demucs failed:\nSTDERR:\n{result.stderr[:1500]}\n"
                    f"STDOUT:\n{result.stdout[:800]}"
                )
                print(f"[Demucs] {detail}", flush=True)
                if callback:
                    callback(24, f"Demucs failed: {result.stderr[:200] or result.stdout[:200]}")
                return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)
        except FileNotFoundError:
            if callback:
                callback(24, "Demucs not found, falling back to FFmpeg...")
            return self._run_ffmpeg_fallback(input_path, output_dir, fmt, callback)
        except subprocess.TimeoutExpired:
            raise Exception("Demucs timed out")

        if callback:
            callback(70, "Moving output files...")

        # Demucs outputs: <model>/<filename>/vocals.wav and no_vocals.wav
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        demucs_result = None
        for root, dirs, files in os.walk(demucs_out):
            if base_name in root:
                demucs_result = root
                break
        if not demucs_result:
            for d in os.listdir(demucs_out):
                sub = os.path.join(demucs_out, d, base_name)
                if os.path.isdir(sub):
                    demucs_result = sub
                    break
        if not demucs_result:
            raise Exception("Demucs output directory not found")

        vocals_src = os.path.join(demucs_result, "vocals.wav")
        bg_src = os.path.join(demucs_result, "no_vocals.wav")
        if not os.path.exists(bg_src):
            for stem in ["drums.wav", "bass.wav", "other.wav"]:
                alt = os.path.join(demucs_result, stem)
                if os.path.exists(alt):
                    bg_src = alt
                    break

        vocals_dst = os.path.join(output_dir, f"vocals.{fmt}")
        bg_dst = os.path.join(output_dir, f"background.{fmt}")
        self._convert_and_move(vocals_src, vocals_dst)
        self._convert_and_move(bg_src, bg_dst)

        return {"vocals": vocals_dst, "background": bg_dst}

    def separate_multi_stem(
        self,
        input_path: str,
        output_dir: str,
        callback: Optional[Callable] = None,
        *,
        model: str = "",
        format: str = "",
        **kwargs,
    ) -> dict:
        """Multi-stem separation (4 or 6 stems). Does NOT pass --two-stems.

        Returns dict like {"vocals": path, "drums": path, "bass": path, ...}.
        """
        if callback:
            callback(20, "Running Demucs multi-stem separation...")

        cfg = self._config
        use_model = model or cfg.get("model", "htdemucs_6s")
        segment = cfg.get("segment", 1200)
        fmt = format or cfg.get("format", "wav")
        timeout = cfg.get("timeout", 1800)

        # Probe demucs runtime
        probe = self._probe_demucs_runtime()
        if callback:
            callback(22, probe["message"])
        if not probe["ok"]:
            raise Exception(f"Demucs unavailable: {probe['message']}")

        demucs_out = os.path.join(output_dir, "demucs_output")
        os.makedirs(demucs_out, exist_ok=True)

        if callback:
            callback(23, f"Loading model {use_model}...")
        model_info = self._ensure_model(use_model)
        if not model_info:
            raise Exception(f"Failed to load model {use_model}")

        model_name, max_segment = model_info
        if max_segment is not None and segment > max_segment:
            segment = int(max_segment)
        elif max_segment is None and segment > 10:
            segment = 7

        # No --two-stems for multi-stem output
        cmd = [
            "demucs",
            "--segment", str(segment),
            "-n", model_name,
            "-o", demucs_out,
            input_path,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, cwd=output_dir
            )
            if result.returncode != 0:
                raise Exception(f"Demucs failed: {result.stderr[:1500]}")
        except FileNotFoundError:
            raise Exception("Demucs command not found")
        except subprocess.TimeoutExpired:
            raise Exception("Demucs timed out")

        if callback:
            callback(70, "Collecting output stems...")

        # Find output directory
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        demucs_result = None
        for root, dirs, files in os.walk(demucs_out):
            if base_name in root and any(f.endswith(".wav") for f in files):
                demucs_result = root
                break
        if not demucs_result:
            for d in os.listdir(demucs_out):
                sub = os.path.join(demucs_out, d, base_name)
                if os.path.isdir(sub):
                    demucs_result = sub
                    break
        if not demucs_result:
            raise Exception("Demucs output directory not found")

        # Collect all stems
        stems = {}
        for stem_file in sorted(os.listdir(demucs_result)):
            if stem_file.endswith(".wav"):
                stem_name = os.path.splitext(stem_file)[0]
                src = os.path.join(demucs_result, stem_file)
                dst = os.path.join(output_dir, f"{stem_name}.{fmt}")
                self._convert_and_move(src, dst)
                stems[stem_name] = dst

        if callback:
            callback(90, f"Collected {len(stems)} stems: {list(stems.keys())}")

        return stems

    def _ensure_model(self, model_name: str):
        """Preload model to _model_cache and return its max segment.

        Sets TORCH_HOME to the project cache dir, then loads the model via
        demucs.pretrained so torch.hub downloads and caches it.  The demucs
        CLI inherits the same TORCH_HOME env var and will use the local copy.
        Returns (model_name, max_segment) on success, None on failure.
        """
        os.environ["TORCH_HOME"] = _MODEL_CACHE
        try:
            from demucs import pretrained
            model = pretrained.get_model(model_name)
            # Transformer models (htdemucs*) have a hard segment limit
            max_seg = getattr(model, "segment", None)
            if max_seg is not None:
                print(f"[Demucs] Model {model_name} max segment: {max_seg:.1f}s", flush=True)
            return (model_name, max_seg)
        except Exception as exc:
            print(f"[Demucs] Model preload failed: {exc}", flush=True)
            return None

    def _probe_demucs_runtime(self):
        """Check if demucs/torch can be imported without DLL errors."""
        cmd = [
            sys.executable, "-c",
            "import torch; import demucs; print('demucs_runtime_ok')",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except Exception as exc:
            return {"ok": False, "message": f"Demucs runtime probe failed: {exc}"}

        if result.returncode == 0:
            return {"ok": True, "message": "Demucs runtime probe passed"}

        detail = (result.stderr or result.stdout or "").strip()
        if "shm.dll" in detail or "WinError 126" in detail:
            return {
                "ok": False,
                "message": "Demucs/Torch runtime unavailable: DLL dependency missing (WinError 126).",
            }
        return {"ok": False, "message": f"Demucs runtime probe failed: {detail[:800]}"}

    def _convert_and_move(self, src, dst):
        """Convert audio format if needed using ffmpeg, otherwise copy."""
        if not os.path.exists(src):
            raise Exception(f"Source file not found: {src}")
        src_ext = os.path.splitext(src)[1].lower().lstrip(".")
        dst_ext = os.path.splitext(dst)[1].lower().lstrip(".")
        if src_ext == dst_ext:
            shutil.copy2(src, dst)
        else:
            cmd = [
                "ffmpeg", "-y", "-i", src,
                "-acodec", "pcm_s16le" if dst_ext == "wav" else "libmp3lame",
                dst,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise Exception(f"Audio conversion failed: {result.stderr[:300]}")

    def _run_ffmpeg_fallback(self, audio_path, output_dir, fmt, callback=None):
        """Emergency fallback using FFmpeg center/side extraction."""
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
