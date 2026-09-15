"""
s19_audio_enhance: Enhance audio via enhancement-capable separation interfaces.

Uses models tagged with ``category == "enhancement"`` (e.g. MDX-NET de-reverb /
denoise models). Unlike vocal separation (which splits into vocals + background),
this step treats the model's isolated output as the *enhanced* signal and exposes
up to three output ports so results from different interfaces can be wired:

    audio       增强后音频（主输出，所有音频增强接口必产出）
    background  残差/副产物（被去除的噪声、混响等；部分接口产出）
    extra       第三路输出（预留，供多路/多轨增强接口使用）
"""
import os
import shutil
import tempfile
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

_AUDIO_EXTS = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus")


class S19AudioEnhance(BaseStep):
    step_id = "s19_audio_enhance"
    step_name = "音频增强"
    dependencies = []

    # ------------------------------------------------------------------
    # Artifacts / validation
    # ------------------------------------------------------------------

    def _suffix(self) -> str:
        node_id = getattr(self, "_node_id", "") or ""
        return f"_{node_id}" if node_id else ""

    @property
    def artifacts(self):
        s = self._suffix()
        return [f"output/enhanced{s}.*", f"output/residual{s}.*"]

    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(output_dir):
            return False
        s = self._suffix()
        return any(name.startswith(f"enhanced{s}.") for name in os.listdir(output_dir))

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve_audio_path(getattr(self, "_step_inputs", {}) or {}, task_dir))

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Preparing audio enhancement...")

        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        audio_path = self._resolve_audio_path(step_inputs, task_dir)
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(
                "音频增强输入音频不存在。请检查上游连线是否正确连接音频。"
            )

        iface_id = node_config.get("method") or self._get_default_interface()
        model = node_config.get("model") or self._default_enhance_model(iface_id)
        fmt = str(node_config.get("format") or "wav").lower().lstrip(".")

        # Soft guard: warn when the selected model is not an enhancement model,
        # so users notice a vocal/instrument model is being used here.
        category = self._model_category(iface_id, model)
        if callback and category and category != "enhancement":
            callback(8, f"提示：模型 {model} 非音频增强模型（类别={category}），增强效果可能不符合预期")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        if callback:
            callback(10, f"Running enhancement via {iface_id} / {model or 'default'}...")

        from backend.separation.separation_factory import get_separation_engine
        engine = get_separation_engine(iface_id)
        temp_dir = tempfile.mkdtemp(prefix="audio_enhance_", dir=task_dir)
        try:
            result = engine.separate(audio_path, temp_dir, callback, model=model, format=fmt)

            if cancel_callback and cancel_callback():
                from backend.control_plane.runtime import TaskCancelledError
                raise TaskCancelledError("Cancelled by user")

            s = self._suffix()

            # Primary enhanced audio. Enhancement interfaces expose the processed
            # signal under "vocals"; fall back to any available stem.
            primary_src = result.get("vocals", "") or result.get("audio", "") or result.get("enhanced", "")
            residual_src = result.get("background", "")
            extra_src = result.get("extra", "")

            final_primary = os.path.join(output_dir, f"enhanced{s}.{fmt}")
            final_residual = os.path.join(output_dir, f"residual{s}.{fmt}")
            final_extra = os.path.join(output_dir, f"extra{s}.{fmt}")

            produced = {}
            for src, target, key in (
                (primary_src, final_primary, "audio"),
                (residual_src, final_residual, "background"),
                (extra_src, final_extra, "extra"),
            ):
                if src and os.path.exists(src):
                    if os.path.exists(target):
                        os.remove(target)
                    shutil.move(src, target)
                    produced[key] = target

            if not os.path.exists(final_primary):
                raise FileNotFoundError("音频增强未生成增强后的音频产物")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        rel_residual = f"output/residual{s}.{fmt}" if os.path.exists(final_residual) else ""
        rel_extra = f"output/extra{s}.{fmt}" if os.path.exists(final_extra) else ""

        outputs = {"audio": f"output/enhanced{s}.{fmt}"}
        if rel_residual:
            outputs["background"] = rel_residual
        if rel_extra:
            outputs["extra"] = rel_extra

        if callback:
            callback(100, "Audio enhancement completed")

        return {
            "artifacts": list(outputs.values()),
            "outputs": outputs,
            "output_enhanced": final_primary,
            "output_residual": rel_residual,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_audio_path(step_inputs: dict, task_dir: str) -> str:
        """Resolve input audio from upstream connection, else scan cache dir."""
        audio_path = step_inputs.get("audio", "")
        if audio_path:
            p = audio_path if os.path.isabs(audio_path) else os.path.join(task_dir, audio_path)
            if os.path.exists(p):
                return p

        cache_dir = os.path.join(task_dir, "cache")
        if os.path.exists(cache_dir):
            for f in sorted(os.listdir(cache_dir)):
                if f.startswith("input_audio") or f.endswith(_AUDIO_EXTS):
                    return os.path.join(cache_dir, f)
        return ""

    @staticmethod
    def _get_default_interface() -> str:
        """Pick a default interface that actually offers enhancement models.

        The globally configured separation interface is only reused when it
        supports enhancement; otherwise the first enhancement-capable enabled
        interface wins (e.g. mdx_net_onnx).
        """
        try:
            from backend.separation.separation_interface_manager import get_separation_interface_manager

            mgr = get_separation_interface_manager()
            enabled = mgr.get_enabled()

            def has_enhance(iface):
                details = (iface.get("config") or {}).get("model_details") or {}
                return any((d or {}).get("category") == "enhancement" for d in details.values())

            configured = ""
            try:
                from backend.config.config_manager import config
                configured = config.get("separation", {}).get("method") or ""
            except Exception:
                configured = ""

            for iface in enabled:
                if iface.get("id") == configured and has_enhance(iface):
                    return configured
            for iface in enabled:
                if has_enhance(iface):
                    return iface.get("id", "")
        except Exception:
            pass
        return "mdx_net_onnx"

    @staticmethod
    def _default_enhance_model(iface_id: str) -> str:
        """Pick the interface's first enhancement-category model.

        Avoids silently running a vocal model (the engine's own default) when
        the node leaves the model unset.
        """
        try:
            from backend.separation.separation_interface_manager import get_separation_interface_manager
            mgr = get_separation_interface_manager()
            cfg = (mgr.get(iface_id) or {}).get("config", {})
            details = cfg.get("model_details", {}) or {}
            for model_id, detail in details.items():
                if (detail or {}).get("category") == "enhancement":
                    return model_id
        except Exception:
            pass
        return ""

    @staticmethod
    def _model_category(iface_id: str, model: str) -> str:
        """Return the declared category of a model, empty when unknown."""
        if not model:
            return ""
        try:
            from backend.separation.separation_interface_manager import get_separation_interface_manager
            mgr = get_separation_interface_manager()
            cfg = (mgr.get(iface_id) or {}).get("config", {})
            return (cfg.get("model_details", {}).get(model) or {}).get("category", "")
        except Exception:
            return ""
