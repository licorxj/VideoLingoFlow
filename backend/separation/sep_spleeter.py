"""Spleeter separation engine: wraps the spleeter CLI for vocal/background separation."""
import os
import shutil
import subprocess
from typing import Callable, Optional

from backend.separation.sep_base import SeparationBase
from backend.separation.separation_interface_manager import get_separation_interface_manager


class SpleeterSeparation(SeparationBase):
    """Vocal separation using Spleeter CLI (2stems / 4stems / 5stems)."""

    def __init__(self, iface_id: str = "spleeter"):
        mgr = get_separation_interface_manager()
        iface = mgr.get(iface_id) or mgr.get("spleeter")
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
            callback(20, "Running Spleeter separation...")

        cfg = self._config
        use_model = model or cfg.get("model", "2stems")
        fmt = format or cfg.get("format", "wav")
        timeout = cfg.get("timeout", 1200)

        spleeter_out = os.path.join(output_dir, "spleeter_output")
        os.makedirs(spleeter_out, exist_ok=True)

        cmd = [
            "spleeter", "separate",
            "-p", f"spleeter:{use_model}",
            "-o", spleeter_out,
            input_path,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, cwd=output_dir
            )
            if result.returncode != 0:
                raise Exception(f"Spleeter failed: {result.stderr[:500]}")
        except FileNotFoundError:
            raise Exception("spleeter not found. Install with: pip install spleeter")
        except subprocess.TimeoutExpired:
            raise Exception("Spleeter timed out")

        if callback:
            callback(70, "Moving output files...")

        # Spleeter outputs: <filename>/vocals.wav and <filename>/accompaniment.wav
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        spleeter_result = os.path.join(spleeter_out, base_name)
        if not os.path.exists(spleeter_result):
            for d in os.listdir(spleeter_out):
                if os.path.isdir(os.path.join(spleeter_out, d)):
                    spleeter_result = os.path.join(spleeter_out, d)
                    break

        vocals_src = os.path.join(spleeter_result, "vocals.wav")
        bg_src = os.path.join(spleeter_result, "accompaniment.wav")

        vocals_dst = os.path.join(output_dir, f"vocals.{fmt}")
        bg_dst = os.path.join(output_dir, f"background.{fmt}")

        self._convert_and_move(vocals_src, vocals_dst)
        self._convert_and_move(bg_src, bg_dst)

        return {"vocals": vocals_dst, "background": bg_dst}

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
