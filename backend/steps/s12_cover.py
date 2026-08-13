"""s12_cover: AI cover design - generate text-to-image prompt from content JSON."""
import json
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.llm.llm_client import get_llm_client
from backend.prompts.prompt_service import get_prompt_service


class S12Cover(BaseStep):
    step_id = "s12_cover"
    step_name = "AI封面设计"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        path = os.path.join(task_dir, "output", f"cover_prompt_{node_id}.txt")
        return os.path.exists(path)

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. Read upstream JSON and extract fields ---
        if callback:
            callback(10, "Reading content JSON...")

        json_path = step_inputs.get("json", "")
        if not json_path:
            raise ValueError("No JSON input connected. Please connect an upstream JSON output.")

        # Resolve path
        if not os.path.isabs(json_path):
            json_path = os.path.join(task_dir, json_path)
        if not os.path.isfile(json_path):
            raise FileNotFoundError(f"JSON input file not found: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            content = json.load(f)

        # Support both "title" and "tittle" spellings
        json_title = content.get("title") or content.get("tittle") or ""
        json_hook = content.get("hook") or ""
        json_summary = content.get("summary") or content.get("summerize") or content.get("summarize") or ""

        if not json_title and not json_summary:
            raise ValueError("Input JSON must contain at least 'title' (or 'tittle') and 'summary' fields.")

        # --- 2. Determine final title and subtitle ---
        custom_title_enabled = node_config.get("custom_title_enabled", False)
        custom_title = node_config.get("custom_title", "")
        custom_subtitle_enabled = node_config.get("custom_subtitle_enabled", False)
        custom_subtitle = node_config.get("custom_subtitle", "")

        title = custom_title if (custom_title_enabled and custom_title) else json_title
        subtitle = custom_subtitle if (custom_subtitle_enabled and custom_subtitle) else json_hook

        if callback:
            callback(30, f"Title: {title}, Subtitle: {subtitle}")

        # --- 3. Generate cover prompt ---
        design_mode = node_config.get("design_mode", "ai_design")
        # chips returns array, extract first value
        if isinstance(design_mode, list):
            design_mode = design_mode[0] if design_mode else "ai_design"

        if design_mode == "ai_design":
            # AI mode: use LLM to design the prompt
            if callback:
                callback(40, "Requesting AI cover design...")

            svc = get_prompt_service()
            prompt_bundle = svc.assemble_prompt("s12_cover", {
                "title": title,
                "subtitle": subtitle,
                "summary": json_summary
            })

            llm = get_llm_client()
            try:
                result = llm.chat(
                    step_name="s12_cover",
                    prompt=prompt_bundle["user_prompt"],
                    response_json=False,
                    stream=False,
                    log=True,
                    system_prompt=prompt_bundle["system_prompt"],
                )
                cover_prompt = str(result).strip()
            except Exception as e:
                raise RuntimeError(f"AI cover design failed: {e}") from e
        else:
            # Custom prompt mode: replace placeholders
            custom_prompt = node_config.get("custom_prompt", "")
            if not custom_prompt:
                raise ValueError("Custom prompt is empty. Please enter a text-to-image prompt.")
            cover_prompt = custom_prompt.replace("{title}", title)
            cover_prompt = cover_prompt.replace("{subtitle}", subtitle)

        if callback:
            callback(80, "Saving cover prompt...")

        # --- 4. Save output ---
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"cover_prompt_{node_id}.txt"
        output_path = os.path.join(output_dir, output_filename)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(cover_prompt)

        if callback:
            callback(100, f"Cover prompt saved: {output_filename}")

        return {
            "artifacts": [f"output/{output_filename}"],
            "outputs": {
                "prompt": f"output/{output_filename}",
                "text": cover_prompt,
            },
        }
