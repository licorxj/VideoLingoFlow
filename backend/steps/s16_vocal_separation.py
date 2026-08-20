"""
s16_vocal_separation: Separate vocals and background music from audio.
Delegates to the separation service layer (factory → interface implementation).
"""
import os
import shutil
import tempfile
from typing import Callable, Optional
from backend.steps.base_step import BaseStep


class StepVocalSeparation(BaseStep):
    step_id = "s16_vocal_separation"
    step_name = "人声分离"
    dependencies = []

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/vocals{node_suffix}.*", f"output/background{node_suffix}.*"]

    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        vocals_prefix = f"vocals{node_suffix}."
        background_prefix = f"background{node_suffix}."
        names = os.listdir(output_dir) if os.path.isdir(output_dir) else []
        return any(name.startswith(vocals_prefix) for name in names) and any(
            name.startswith(background_prefix) for name in names
        )

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        # 优先检查上游连线传入的音频路径
        audio_input = step_inputs.get("audio", "")
        if audio_input:
            p = audio_input if os.path.isabs(audio_input) else os.path.join(task_dir, audio_input)
            if os.path.exists(p):
                return True
        # 回退：扫描 cache 目录
        cache_dir = os.path.join(task_dir, "cache")
        return any(
            f.startswith("input_audio") or f.endswith((".wav", ".mp3", ".flac", ".m4a"))
            for f in os.listdir(cache_dir)
        ) if os.path.exists(cache_dir) else False

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Preparing vocal separation...")

        step_inputs = getattr(self, "_step_inputs", {}) or {}
        node_config = getattr(self, "_node_config", {}) or {}

        # Interface ID: node_config.method → global setting → default "spleeter"
        iface_id = node_config.get("method") or self._get_default_interface()
        model = node_config.get("model", "")
        fmt = str(node_config.get("format") or "wav").lower().lstrip(".")

        # 优先使用上游连线传入的音频路径
        audio_path = step_inputs.get("audio", "")
        if audio_path and not os.path.isabs(audio_path):
            audio_path = os.path.join(task_dir, audio_path)
        if audio_path and os.path.exists(audio_path):
            print(f"[VocalSeparation] Using upstream audio: {audio_path}")
        else:
            # 回退：扫描 cache 目录
            audio_path = ""
            cache_dir = os.path.join(task_dir, "cache")
            if os.path.exists(cache_dir):
                for f in os.listdir(cache_dir):
                    if f.startswith("input_audio") or f.endswith((".wav", ".mp3", ".flac", ".m4a")):
                        audio_path = os.path.join(cache_dir, f)
                        break
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(
                f"人声分离输入音频不存在。请检查上游连线是否正确连接音频。"
            )

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Cancel check before starting separation
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        if callback:
            callback(10, f"Running separation via {iface_id}...")

        # Delegate to separation service layer
        from backend.separation.separation_factory import get_separation_engine
        engine = get_separation_engine(iface_id)
        temp_dir = tempfile.mkdtemp(prefix="vocal_separation_", dir=task_dir)
        try:
            result = engine.separate(audio_path, temp_dir, callback, model=model, format=fmt)

            if cancel_callback and cancel_callback():
                from backend.control_plane.runtime import TaskCancelledError
                raise TaskCancelledError("Cancelled by user")

            vocals_path = result.get("vocals", "")
            bg_path = result.get("background", "")

            node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
            final_vocals = os.path.join(output_dir, f"vocals{node_suffix}.{fmt}")
            final_background = os.path.join(output_dir, f"background{node_suffix}.{fmt}")
            for source, target in ((vocals_path, final_vocals), (bg_path, final_background)):
                if source and os.path.exists(source):
                    if os.path.exists(target):
                        os.remove(target)
                    shutil.move(source, target)
            if not os.path.exists(final_vocals) or not os.path.exists(final_background):
                raise FileNotFoundError("人声分离未生成完整的最终音频产物")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        if callback:
            callback(100, "Vocal separation completed")

        return {
            "artifacts": [f"output/vocals{node_suffix}.{fmt}", f"output/background{node_suffix}.{fmt}"],
            "outputs": {
                "audio": f"output/vocals{node_suffix}.{fmt}",
                "background": f"output/background{node_suffix}.{fmt}",
            },
            "output_vocals": final_vocals,
            "output_background": final_background,
        }

    @staticmethod
    def _get_default_interface() -> str:
        """Read default separation interface from global settings."""
        try:
            from backend.config.config_manager import config
            return config.get("separation", {}).get("method") or "spleeter"
        except Exception:
            return "spleeter"
