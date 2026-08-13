"""s_imagegen: AI image generation node using the imagegen service layer."""
import os
import shutil
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


def _read_input_as_text(value, task_dir: str = "") -> str:
    """Resolve input: if it's a file path, read its content; otherwise return as-is."""
    if not value or not isinstance(value, str):
        return str(value) if value else ""
    candidate = value.strip()
    if os.path.isfile(candidate):
        with open(candidate, "r", encoding="utf-8") as f:
            return f.read().strip()
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            with open(rel, "r", encoding="utf-8") as f:
                return f.read().strip()
    return value.strip()


def _resolve_image_path(value, task_dir: str = "") -> str:
    """Resolve an image file path to absolute path."""
    if not value or not isinstance(value, str):
        return ""
    candidate = value.strip()
    if os.path.isfile(candidate):
        return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            return rel
    return ""


class S_ImageGen(BaseStep):
    step_id = "s_imagegen"
    step_name = "AI生图"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        output_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(output_dir):
            return False
        for f in os.listdir(output_dir):
            if f.endswith(f"_gen_image_{node_id}") or f"_gen_image_{node_id}." in f:
                return True
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. Read config ---
        mode = node_config.get("mode", "txt2img")
        # chips returns array
        if isinstance(mode, list):
            mode = mode[0] if mode else "txt2img"

        interface = node_config.get("interface", "")
        if isinstance(interface, list):
            interface = interface[0] if interface else ""

        model = node_config.get("model", "")
        resolution = node_config.get("resolution", "1K")
        aspect_ratio = node_config.get("aspect_ratio", "1:1")
        num_images = int(node_config.get("num_images", 1))
        custom_prompt_enabled = node_config.get("custom_prompt_enabled", False)
        custom_prompt = node_config.get("custom_prompt", "")
        output_prefix = node_config.get("output_prefix", "img") or "img"

        if not interface:
            raise ValueError("No interface selected. Please select an image generation interface.")

        # --- 2. Resolve prompt ---
        if custom_prompt_enabled and custom_prompt:
            prompt = custom_prompt.strip()
        else:
            raw_text = step_inputs.get("text", "")
            prompt = _read_input_as_text(raw_text, task_dir)

        if not prompt:
            raise ValueError("Prompt is empty. Please connect a text input or enable custom prompt.")

        # --- 3. Resolve image input for img2img ---
        ref_images = []
        if mode == "img2img":
            raw_image = step_inputs.get("image", "")
            image_path = _resolve_image_path(raw_image, task_dir)
            if not image_path:
                raise ValueError("Image-to-image mode requires an image input, but no valid image found.")
            ref_images = [image_path]

        if callback:
            callback(20, f"Generating images ({mode}, {model or 'default'}, {resolution}, {aspect_ratio})...")

        # --- 4. Get engine and generate ---
        from backend.imagegen.imagegen_factory import get_imagegen_engine

        engine = get_imagegen_engine(interface)
        if not engine:
            raise RuntimeError(f"Failed to create imagegen engine for interface '{interface}'.")

        # Create temp output dir for raw generation
        temp_dir = os.path.join(task_dir, "output", f"_imggen_temp_{node_id}")
        os.makedirs(temp_dir, exist_ok=True)

        if callback:
            callback(40, "Calling image generation engine...")

        try:
            result_paths = engine.generate(
                prompt=prompt,
                output_dir=temp_dir,
                model=model,
                mode=mode,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                num_images=num_images,
                ref_images=ref_images if ref_images else None,
            )
        except Exception as e:
            raise RuntimeError(f"Image generation failed: {e}") from e

        if not result_paths:
            raise RuntimeError("Image generation returned no results. Check interface configuration and logs.")

        if callback:
            callback(80, f"Generated {len(result_paths)} image(s), renaming...")

        # --- 5. Rename output files ---
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        final_paths = []

        for i, src_path in enumerate(result_paths):
            if not os.path.exists(src_path):
                continue
            ext = os.path.splitext(src_path)[1] or ".png"
            dest_name = f"{output_prefix}_{i + 1}_gen_image_{node_id}{ext}"
            dest_path = os.path.join(output_dir, dest_name)
            shutil.copy2(src_path, dest_path)
            final_paths.append(f"output/{dest_name}")

        # Clean up temp dir
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        if not final_paths:
            raise RuntimeError("All generated images failed to save.")

        if callback:
            callback(100, f"Saved {len(final_paths)} image(s)")

        return {
            "artifacts": list(final_paths),
            "outputs": {
                "images": str(final_paths),
                "text": final_paths[0] if final_paths else "",
            },
        }
