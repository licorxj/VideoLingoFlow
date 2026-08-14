"""
s16_vocal_separation: Separate vocals and background music from audio.
Delegates to the separation service layer (factory → interface implementation).
"""
import os
import shutil
from typing import Callable, Optional
from backend.steps.base_step import BaseStep, find_artifact


class StepVocalSeparation(BaseStep):
    step_id = "s16_vocal_separation"
    step_name = "人声分离"
    dependencies = []

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/vocals{node_suffix}.wav", f"output/background{node_suffix}.wav"]

    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        return bool(
            find_artifact(output_dir, "vocals.wav")
            and find_artifact(output_dir, "background.wav")
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
        # 音频质量：节点优先、全局设置兜底（格式/采样率/位深/声道/码率）
        from backend.utils.audio_quality import resolve_audio_quality, reencode_audio
        quality = resolve_audio_quality(node_config)
        fmt = quality["format"]

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
        result = engine.separate(audio_path, output_dir, callback, model=model, format=fmt)

        # Cancel check after separation completes
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        vocals_path = result.get("vocals", "")
        bg_path = result.get("background", "")

        # 输出产物按节点唯一 id 命名，避免同一类型节点互相覆盖
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        final_vocals = os.path.join(output_dir, f"vocals{node_suffix}.{fmt}")
        final_background = os.path.join(output_dir, f"background{node_suffix}.{fmt}")
        # 节点显式设置了采样率/位深/声道/码率时，即使扩展名相同也强制按目标参数转码
        # （format 默认值不算显式设置，仅当扩展名不同时按格式转码）
        node_explicit_quality = any(
            str(node_config.get(k) or "").strip()
            for k in ("sample_rate", "bit_depth", "channels", "bitrate")
        )
        if vocals_path and os.path.exists(vocals_path) and os.path.abspath(vocals_path) != os.path.abspath(final_vocals):
            same_ext = os.path.splitext(vocals_path)[1].lower() == f".{fmt}"
            if same_ext and not node_explicit_quality:
                shutil.move(vocals_path, final_vocals)
            else:
                if callback:
                    callback(70, f"按目标质量转码人声 ({fmt})...")
                reencode_audio(vocals_path, final_vocals, quality)
        if bg_path and os.path.exists(bg_path) and os.path.abspath(bg_path) != os.path.abspath(final_background):
            same_ext = os.path.splitext(bg_path)[1].lower() == f".{fmt}"
            if same_ext and not node_explicit_quality:
                shutil.move(bg_path, final_background)
            else:
                if callback:
                    callback(75, f"按目标质量转码背景 ({fmt})...")
                reencode_audio(bg_path, final_background, quality)

        # Copy to cache/ with node_id prefix for artifact scanner
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        if os.path.exists(final_vocals):
            shutil.copy2(final_vocals, os.path.join(cache_dir, f"vocal_separation_audio{node_suffix}.{fmt}"))
        if os.path.exists(final_background):
            shutil.copy2(final_background, os.path.join(cache_dir, f"vocal_separation_background{node_suffix}.{fmt}"))

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
