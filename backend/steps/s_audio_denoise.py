"""
s_audio_denoise: Denoise audio to remove environmental noise, hum, hiss, etc.
Uses FFmpeg built-in filters (afftdn / highpass / lowpass) for fast processing.
"""
import os
import subprocess
from typing import Callable, Optional
from backend.steps.base_step import BaseStep


class StepAudioDenoise(BaseStep):
    step_id = "s_audio_denoise"
    step_name = "声音降噪"
    dependencies = []

    # 输出格式 -> ffmpeg 编码参数
    FORMAT_ENCODE_ARGS = {
        "wav": ["-acodec", "pcm_s16le"],
        "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
        "flac": ["-c:a", "flac"],
    }

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/denoised_audio{node_suffix}.*"]

    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(output_dir):
            return False
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return any(
            name.startswith(f"denoised_audio{node_suffix}") for name in os.listdir(output_dir)
        )

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        audio_input = step_inputs.get("audio", "")
        if audio_input:
            p = audio_input if os.path.isabs(audio_input) else os.path.join(task_dir, audio_input)
            if os.path.exists(p):
                return True
        cache_dir = os.path.join(task_dir, "cache")
        if os.path.exists(cache_dir):
            for f in os.listdir(cache_dir):
                if f.endswith((".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus")):
                    return True
        return False

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Preparing audio denoise...")

        step_inputs = getattr(self, "_step_inputs", {}) or {}
        node_config = getattr(self, "_node_config", {}) or {}

        # --- resolve input audio path ---
        audio_path = self._resolve_audio_path(step_inputs, task_dir)
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(
                "声音降噪输入音频不存在。请检查上游连线是否正确连接音频。"
            )

        method = node_config.get("method", "ffmpeg")
        noise_level = float(node_config.get("noise_reduction_level", 0.5))
        highpass_freq = int(node_config.get("highpass_freq", 0) or 0)
        lowpass_freq = int(node_config.get("lowpass_freq", 0) or 0)
        target_fmt = str(node_config.get("output_format", "wav")).strip().lower()
        custom_command = str(node_config.get("custom_command", "")).strip()

        # determine output format
        if target_fmt in ("", "auto"):
            target_fmt = self._detect_audio_ext(audio_path) or "wav"
        if target_fmt not in self.FORMAT_ENCODE_ARGS:
            target_fmt = "wav"

        # build output paths
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        output_path = os.path.join(output_dir, f"denoised_audio{node_suffix}.{target_fmt}")

        # cancel check
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        if callback:
            callback(10, f"Running denoise via {method}...")

        # --- build and execute ffmpeg command ---
        cmd = self._build_ffmpeg_cmd(
            audio_path, output_path, method, noise_level,
            highpass_freq, lowpass_freq, custom_command,
        )

        if callback:
            callback(30, "Executing ffmpeg denoise filter...")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                stderr = result.stderr or ""
                lines = stderr.strip().split("\n")
                error_lines = []
                skip_header = True
                for line in lines:
                    if skip_header and (
                        line.startswith("ffmpeg version")
                        or line.startswith("  built with")
                        or line.startswith("  configuration:")
                        or line.startswith("  lib")
                    ):
                        continue
                    skip_header = False
                    if line.strip():
                        error_lines.append(line.strip())
                error_msg = "\n".join(error_lines[-5:]) if error_lines else stderr[-300:]
                raise Exception("ffmpeg denoise failed:\n" + error_msg)
        except subprocess.TimeoutExpired:
            raise Exception("Audio denoise timed out after 10 minutes")
        except FileNotFoundError:
            raise Exception(
                "ffmpeg not found. Please install ffmpeg or place ffmpeg.exe in the venv Scripts directory."
            )

        # cancel check after processing
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        if callback:
            callback(100, "Audio denoise completed")

        return {
            "artifacts": [f"output/denoised_audio{node_suffix}.{target_fmt}"],
            "outputs": {
                "audio": f"output/denoised_audio{node_suffix}.{target_fmt}",
            },
            "output_path": output_path,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_audio_path(step_inputs: dict, task_dir: str) -> str:
        """Resolve audio path from upstream connection or fallback to cache scan."""
        audio_path = step_inputs.get("audio", "")
        if audio_path:
            p = audio_path if os.path.isabs(audio_path) else os.path.join(task_dir, audio_path)
            if os.path.exists(p):
                return p

        cache_dir = os.path.join(task_dir, "cache")
        if os.path.exists(cache_dir):
            for f in sorted(os.listdir(cache_dir)):
                if f.endswith((".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus")):
                    return os.path.join(cache_dir, f)
        return ""

    @staticmethod
    def _detect_audio_ext(audio_path: str) -> str:
        """Detect audio file extension for format auto-detection."""
        ext = os.path.splitext(audio_path)[1].lower().lstrip(".")
        if ext in ("wav", "mp3", "flac", "m4a", "ogg", "opus"):
            return ext
        return ""

    def _build_ffmpeg_cmd(
        self,
        input_path: str,
        output_path: str,
        method: str,
        noise_level: float,
        highpass_freq: int,
        lowpass_freq: int,
        custom_command: str,
    ) -> list[str]:
        """Build the ffmpeg command line with appropriate filters."""
        filters = []

        if method == "custom" and custom_command:
            # User provides their own filter string
            filters.append(custom_command)
        else:
            # Default: FFT-based denoise (afftdn)
            # noise_level 0~1 -> nr parameter 0~30
            nr = max(0, min(30, int(noise_level * 30)))
            # nf (noise floor in dB): more aggressive when level is high
            nf = -30 + int(noise_level * 10)  # range: -30 to -20
            filters.append(f"afftdn=nf={nf}:nr={nr}:nt=w")

            if highpass_freq > 0:
                filters.append(f"highpass=f={highpass_freq}")

            if lowpass_freq > 0:
                filters.append(f"lowpass=f={lowpass_freq}")

        filter_chain = ",".join(filters)

        encode_args = self.FORMAT_ENCODE_ARGS.get(
            os.path.splitext(output_path)[1].lstrip("."),
            ["-acodec", "pcm_s16le"],
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", filter_chain,
            *encode_args,
            output_path,
        ]
        return cmd
