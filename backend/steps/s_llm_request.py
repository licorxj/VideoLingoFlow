"""s_llm_request: Generic LLM request node with configurable prompts, model, and output format."""
import json
import os
import re
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.llm.llm_client import get_llm_client


def _read_input_value(value, task_dir: str = "") -> str:
    """Resolve an input value: if it's a file path that exists, read its content; otherwise return as-is."""
    if not value or not isinstance(value, str):
        return str(value) if value else ""
    # Try as absolute path first, then relative to task_dir
    candidate = value.strip()
    if os.path.isfile(candidate):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(candidate, "r", encoding="utf-8-sig") as f:
                return f.read()
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            try:
                with open(rel, "r", encoding="utf-8") as f:
                    return f.read()
            except UnicodeDecodeError:
                with open(rel, "r", encoding="utf-8-sig") as f:
                    return f.read()
    return value


def _resolve_file_path(value, task_dir: str = "") -> str:
    """Resolve a file path: return absolute path if file exists, empty string otherwise."""
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


def _load_json_input(raw_json, task_dir: str = ""):
    """Load JSON from file path, string, or pass through dict/list."""
    if raw_json is None:
        return None
    if isinstance(raw_json, (dict, list)):
        return raw_json
    if not isinstance(raw_json, str) or not raw_json.strip():
        return None
    candidate = raw_json.strip()
    # Try as file path
    path = candidate
    if not os.path.isabs(path) and task_dir:
        path = os.path.join(task_dir, candidate)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Try as JSON string
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None


def _apply_json_placeholder(prompt: str, json_data) -> str:
    """Replace {input_json} and {input_json}[key0][key1]... placeholders.

    - {input_json} -> full JSON as text
    - {input_json}[key0][key1] -> extract nested value by keys
    """
    if json_data is None:
        return prompt

    # Pattern: {input_json} optionally followed by [key] segments
    pattern = re.compile(r'\{input_json\}((?:\[[^\]]+\])*)')

    def replacer(match):
        keys_str = match.group(1)
        if not keys_str:
            # No keys -> full JSON as text
            if isinstance(json_data, (dict, list)):
                return json.dumps(json_data, ensure_ascii=False, indent=2)
            return str(json_data)
        # Extract keys from [key0][key1]...
        keys = re.findall(r'\[([^\]]+)\]', keys_str)
        current = json_data
        for key in keys:
            if isinstance(current, dict):
                if key not in current:
                    return f"[ERROR: key '{key}' not found]"
                current = current[key]
            elif isinstance(current, list):
                try:
                    idx = int(key)
                    current = current[idx]
                except (ValueError, IndexError):
                    return f"[ERROR: index '{key}' invalid]"
            else:
                return f"[ERROR: cannot access '{key}' on {type(current).__name__}]"
        if isinstance(current, (dict, list)):
            return json.dumps(current, ensure_ascii=False, indent=2)
        return str(current) if current is not None else ""

    return pattern.sub(replacer, prompt)


class S_LLMRequest(BaseStep):
    step_id = "s_llm_request"
    step_name = "通用LLM请求"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        # Check both possible output extensions
        for ext in ("json", "txt"):
            path = os.path.join(task_dir, "output", f"LLM_{node_id}.{ext}")
            if os.path.exists(path):
                return True
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True  # No strictly required inputs

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # Read config
        system_prompt = node_config.get("system_prompt", "")
        user_prompt = node_config.get("user_prompt", "{input_text}")
        model = node_config.get("model", "")
        temperature = node_config.get("temperature")
        response_json = node_config.get("response_json", False)
        log_request = node_config.get("log_request", False)

        # Get upstream inputs - resolve file paths to actual content
        raw_text = step_inputs.get("text", "")
        raw_image = step_inputs.get("image", "")
        raw_json = step_inputs.get("json", "")
        source_language = step_inputs.get("source_language", "")
        target_language = step_inputs.get("target_language", "")
        input_text = _read_input_value(raw_text, task_dir)
        input_image = _resolve_file_path(raw_image, task_dir)
        json_data = _load_json_input(raw_json, task_dir)

        # Replace placeholders in user_prompt
        actual_prompt = user_prompt.replace("{input_text}", str(input_text))
        actual_prompt = actual_prompt.replace("{source_language}", str(source_language))
        actual_prompt = actual_prompt.replace("{target_language}", str(target_language))
        actual_prompt = _apply_json_placeholder(actual_prompt, json_data)

        if callback:
            callback(20, f"Preparing LLM request (model={model or 'default'}, json={response_json})")

        # Build images list if image input exists
        images = None
        if input_image:
            images = [input_image]
        elif raw_image and isinstance(raw_image, list):
            # Handle list of image paths
            resolved = [_resolve_file_path(p, task_dir) for p in raw_image]
            resolved = [p for p in resolved if p]
            if resolved:
                images = resolved

        # Parse temperature
        temp_val = None
        if temperature is not None:
            try:
                temp_val = float(temperature)
            except (ValueError, TypeError):
                temp_val = None

        if callback:
            callback(40, "Sending LLM request...")

        # Use model override as step_name if provided, otherwise use node step_id
        step_name = model if model else self.step_id

        llm = get_llm_client()
        try:
            result = llm.chat(
                step_name=step_name,
                prompt=actual_prompt,
                response_json=response_json,
                stream=False,
                log=True,
                system_prompt=system_prompt if system_prompt else None,
                temperature=temp_val,
                images=images,
                log_request_params=log_request,
            )
        except Exception as e:
            raise RuntimeError(f"LLM request failed: {e}") from e

        if callback:
            callback(70, "Processing response...")

        # Save output
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        if response_json:
            # JSON output: repair and format
            output_path = os.path.join(output_dir, f"LLM_{node_id}.json")
            if isinstance(result, str):
                # Try to parse and re-format
                try:
                    import json_repair
                    result = json_repair.loads(result)
                except Exception:
                    result = json.loads(result)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            text_output = json.dumps(result, ensure_ascii=False, indent=2)
        else:
            # Text output
            output_path = os.path.join(output_dir, f"LLM_{node_id}.txt")
            text_output = str(result)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text_output)

        if callback:
            callback(100, f"Result saved to {os.path.basename(output_path)}")

        return {
            "artifacts": [f"output/LLM_{node_id}.{('json' if response_json else 'txt')}"],
            "outputs": {
                "result": f"output/LLM_{node_id}.{('json' if response_json else 'txt')}",
                "text": text_output,
            },
        }
