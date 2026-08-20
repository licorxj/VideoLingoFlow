import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.utils.audio_quality import reencode_audio, resolve_audio_quality


class StepAudioTranscode(BaseStep):
    step_id = "s18_audio_transcode"
    step_name = "音频质量转码"
    dependencies = []

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/transcoded_audio{node_suffix}.*"]

    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        prefix = f"transcoded_audio{node_suffix}."
        return os.path.isdir(output_dir) and any(
            name.startswith(prefix) for name in os.listdir(output_dir)
        )

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve_audio_path(task_dir))

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Preparing audio transcoding...")
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        audio_path = self._resolve_audio_path(task_dir)
        if not audio_path:
            raise FileNotFoundError("音频质量转码输入音频不存在。请检查上游连线是否正确连接音频。")

        quality = resolve_audio_quality(getattr(self, "_node_config", {}) or {})
        fmt = str(quality["format"]).lower().lstrip(".")
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        output_path = os.path.join(output_dir, f"transcoded_audio{node_suffix}.{fmt}")

        if callback:
            callback(20, f"Transcoding audio to {fmt}...")
        reencode_audio(audio_path, output_path, quality, callback=callback)

        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")
        if callback:
            callback(100, "Audio transcoding completed")
        output_rel_path = f"output/transcoded_audio{node_suffix}.{fmt}"
        return {
            "artifacts": [output_rel_path],
            "outputs": {"audio": output_rel_path},
            "output_audio": output_path,
        }

    def _resolve_audio_path(self, task_dir: str) -> str:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        audio_path = step_inputs.get("audio", "")
        if audio_path and not os.path.isabs(audio_path):
            audio_path = os.path.join(task_dir, audio_path)
        if audio_path and os.path.exists(audio_path):
            return audio_path
        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.isdir(cache_dir):
            return ""
        for name in os.listdir(cache_dir):
            if name.startswith("input_audio") or name.lower().endswith((".wav", ".mp3", ".flac", ".m4a")):
                return os.path.join(cache_dir, name)
        return ""
