"""
s17_track_separation: Separate audio into 6 tracks (vocals/bass/drums/guitar/piano/other).
Delegates to the separation service layer via separate_multi_stem().
"""
import os
import shutil
from typing import Callable, Optional
from backend.steps.base_step import BaseStep, find_artifact

# Standard 6-stem names that map to output ports
TRACK_STEMS = ["vocals", "bass", "drums", "guitar", "piano", "other"]


class S17TrackSeparation(BaseStep):
    step_id = "s17_track_separation"
    step_name = "音轨分离"
    dependencies = []

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/{s}{node_suffix}.wav" for s in TRACK_STEMS]

    def check_artifact(self, task_dir: str) -> bool:
        fmt = self._get_format()
        output_dir = os.path.join(task_dir, "output")
        return all(
            find_artifact(output_dir, f"{s}.{fmt}")
            for s in TRACK_STEMS
        )

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        audio_input = step_inputs.get("audio", "")
        if audio_input:
            p = audio_input if os.path.isabs(audio_input) else os.path.join(task_dir, audio_input)
            if os.path.exists(p):
                return True
        cache_dir = os.path.join(task_dir, "cache")
        return any(
            f.startswith("input_audio") or f.endswith((".wav", ".mp3", ".flac", ".m4a"))
            for f in os.listdir(cache_dir)
        ) if os.path.exists(cache_dir) else False

    def _get_format(self) -> str:
        node_config = getattr(self, "_node_config", {}) or {}
        return node_config.get("format", "wav")

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Preparing track separation...")

        step_inputs = getattr(self, "_step_inputs", {}) or {}
        node_config = getattr(self, "_node_config", {}) or {}

        iface_id = node_config.get("method") or self._get_default_interface()
        model = node_config.get("model", "")
        fmt = node_config.get("format", "wav")

        # Resolve input audio path
        audio_path = step_inputs.get("audio", "")
        if audio_path and not os.path.isabs(audio_path):
            audio_path = os.path.join(task_dir, audio_path)
        if audio_path and os.path.exists(audio_path):
            print(f"[TrackSeparation] Using upstream audio: {audio_path}")
        else:
            audio_path = ""
            cache_dir = os.path.join(task_dir, "cache")
            if os.path.exists(cache_dir):
                for f in os.listdir(cache_dir):
                    if f.startswith("input_audio") or f.endswith((".wav", ".mp3", ".flac", ".m4a")):
                        audio_path = os.path.join(cache_dir, f)
                        break
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError("音轨分离输入音频不存在。请检查上游连线是否正确连接音频。")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""

        # Cancel check before starting separation
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        if callback:
            callback(10, f"Running multi-stem separation via {iface_id}...")

        # Get engine and run multi-stem separation
        from backend.separation.separation_factory import get_separation_engine
        engine = get_separation_engine(iface_id)

        if not hasattr(engine, "separate_multi_stem"):
            raise Exception(f"接口 {iface_id} 不支持多轨分离，请选择支持多轨的接口（如 demucs）")

        raw_stems = engine.separate_multi_stem(audio_path, output_dir, callback, model=model, format=fmt)

        # Cancel check after separation completes
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        if callback:
            callback(80, "Mapping stems to output tracks...")

        # Map raw stems to standard track names
        # Known stems go to their matching port; unknown stems merge into "other"
        outputs = {}
        artifacts = []
        other_files = []

        for stem_name, stem_path in raw_stems.items():
            if stem_name in TRACK_STEMS:
                # Direct match
                dst = os.path.join(output_dir, f"{stem_name}{node_suffix}.{fmt}")
                if stem_path != dst and os.path.exists(stem_path):
                    shutil.copy2(stem_path, dst)
                outputs[stem_name] = f"output/{stem_name}{node_suffix}.{fmt}"
                artifacts.append(f"output/{stem_name}{node_suffix}.{fmt}")
            else:
                # Unknown stem -> collect for "other"
                other_files.append(stem_path)
                print(f"[TrackSeparation] Unknown stem '{stem_name}' -> merging into 'other'")

        # Build "other" track: if we have an explicit "other" from demucs, use it;
        # otherwise merge unknown stems (or create silence if none)
        if "other" not in outputs:
            if other_files:
                # Use the first unknown stem as "other" (demucs 4-stem models output "other" directly)
                src = other_files[0]
                dst = os.path.join(output_dir, f"other{node_suffix}.{fmt}")
                if src != dst and os.path.exists(src):
                    shutil.copy2(src, dst)
            else:
                # No "other" stem and no unknown stems -> create silence
                self._create_silence(os.path.join(output_dir, f"other{node_suffix}.{fmt}"), audio_path)
            outputs["other"] = f"output/other{node_suffix}.{fmt}"
            artifacts.append(f"output/other{node_suffix}.{fmt}")

        # Ensure all 6 tracks exist
        for stem in TRACK_STEMS:
            if stem not in outputs:
                # Missing stem (e.g., 4-stem model missing guitar/piano) -> create silence
                self._create_silence(os.path.join(output_dir, f"{stem}{node_suffix}.{fmt}"), audio_path)
                outputs[stem] = f"output/{stem}{node_suffix}.{fmt}"
                artifacts.append(f"output/{stem}{node_suffix}.{fmt}")

        # Copy to cache for artifact scanner
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        for stem in TRACK_STEMS:
            src = os.path.join(output_dir, f"{stem}{node_suffix}.{fmt}")
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(cache_dir, f"track_separation_{stem}.{fmt}"))

        if callback:
            callback(100, f"Track separation completed: {list(outputs.keys())}")

        return {
            "artifacts": artifacts,
            "outputs": outputs,
        }

    @staticmethod
    def _create_silence(output_path: str, reference_audio: str):
        """Create a silent audio file matching the reference audio duration."""
        import subprocess
        # Get duration from reference
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", reference_audio],
                capture_output=True, text=True, timeout=30
            )
            duration = float(probe.stdout.strip())
        except Exception:
            duration = 1.0

        fmt = os.path.splitext(output_path)[1].lstrip(".")
        codec = "pcm_s16le" if fmt == "wav" else "libmp3lame"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
             "-t", str(duration), "-acodec", codec, output_path],
            capture_output=True, text=True, timeout=60
        )

    @staticmethod
    def _get_default_interface() -> str:
        try:
            from backend.config.config_manager import config
            return config.get("separation", {}).get("method") or "demucs"
        except Exception:
            return "demucs"
