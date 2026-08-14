"""s_json_editor: Edit a specific key in a JSON file and overwrite it."""
import json
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


def _resolve_path(value, task_dir: str = "") -> str:
    """Resolve a value to an absolute file path if possible."""
    if not value or not isinstance(value, str):
        return ""
    candidate = value.strip()
    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            return rel
    return ""


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _set_by_key_expr(data, key_expr: str, value):
    """Set value in nested dict using '$'-separated key expression.

    e.g. "a$b$c" -> data["a"]["b"]["c"] = value
    Returns (modified_data, actual_path_list).
    """
    keys = [k.strip() for k in key_expr.split("$") if k.strip()]
    if not keys:
        raise ValueError("key表达式为空")

    current = data
    path_taken = []
    for i, key in enumerate(keys[:-1]):
        if isinstance(current, dict):
            if key not in current:
                raise KeyError(f"键 '{key}' 不存在于: {list(current.keys())}")
            current = current[key]
        elif isinstance(current, list):
            try:
                idx = int(key)
            except ValueError:
                raise KeyError(f"无法将 '{key}' 转为数组索引")
            if idx < 0 or idx >= len(current):
                raise IndexError(f"索引 {idx} 超出数组范围 (长度 {len(current)})")
            current = current[idx]
        else:
            raise TypeError(f"无法在 {type(current).__name__} 上取键 '{key}'")
        path_taken.append(key)

    # Set the final key
    final_key = keys[-1]
    if isinstance(current, dict):
        current[final_key] = value
        path_taken.append(final_key)
    elif isinstance(current, list):
        try:
            idx = int(final_key)
        except ValueError:
            raise KeyError(f"无法将 '{final_key}' 转为数组索引")
        if idx < 0 or idx >= len(current):
            raise IndexError(f"索引 {idx} 超出数组范围 (长度 {len(current)})")
        current[idx] = value
        path_taken.append(final_key)
    else:
        raise TypeError(f"无法在 {type(current).__name__} 上设置键 '{final_key}'")

    return data, path_taken


def _read_text_input(text_input, task_dir: str) -> str:
    """Read text value from input. Could be a file path or direct text."""
    if not text_input:
        return ""
    # Try as file path first
    text_path = _resolve_path(text_input, task_dir)
    if text_path:
        with open(text_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    # Otherwise treat as direct text
    return str(text_input).strip()


class S_JsonEditor(BaseStep):
    step_id = "s_json_editor"
    step_name = "JSON编辑"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # We overwrite the source JSON, so no separate artifact to check
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        key_expr = node_config.get("key_expr", "").strip()
        value_source = node_config.get("value_source", "auto")
        custom_value = node_config.get("custom_value", "")

        if not key_expr:
            raise ValueError("未设置 key 表达式，请在节点配置中填写（如 key0$key1$key2）")

        # --- Resolve JSON input ---
        json_input = step_inputs.get("json", "")
        if not json_input:
            raise ValueError("未连接 JSON 输入。")

        json_path = _resolve_path(json_input, task_dir)
        if json_path:
            data = _read_json(json_path)
            source_path = json_path
        elif isinstance(json_input, str):
            try:
                data = json.loads(json_input)
                source_path = ""
            except json.JSONDecodeError:
                raise ValueError(f"输入既不是有效文件路径，也不是合法 JSON 字符串: {json_input[:100]}")
        else:
            data = json_input
            source_path = ""

        if callback:
            callback(20, f"已读取 JSON，准备修改 key: {key_expr}")

        # --- Resolve text value ---
        text_input = step_inputs.get("text", "")
        text_value = _read_text_input(text_input, task_dir)

        # Determine which value to use based on value_source
        final_value = None
        if value_source == "input":
            if not text_value:
                print(f"[JsonEditor] Warning: value_source='input' but no connection value, skipping", flush=True)
            final_value = text_value if text_value else None
        elif value_source == "custom":
            final_value = custom_value if custom_value else None
        else:  # auto
            # Prefer connection input, fallback to custom
            final_value = text_value if text_value else (custom_value if custom_value else None)

        if final_value is None:
            print(f"[JsonEditor] Warning: no value available (input='{text_value}', custom='{custom_value}'), outputting original JSON", flush=True)
            if callback:
                callback(100, "警告：无可用修改值，输出原 JSON")
            # Output original JSON path
            if source_path:
                return {
                    "artifacts": [],
                    "outputs": {"json": source_path},
                }
            else:
                # Write original to output file
                output_dir = os.path.join(task_dir, "output")
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir, f"json_edit_{node_id}.json")
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                return {
                    "artifacts": [f"output/json_edit_{node_id}.json"],
                    "outputs": {"json": f"output/json_edit_{node_id}.json"},
                }

        # --- Try to parse as JSON, otherwise keep as string ---
        try:
            parsed_value = json.loads(final_value)
        except (json.JSONDecodeError, TypeError):
            parsed_value = final_value

        if callback:
            callback(50, f"修改 key={key_expr}，值={str(parsed_value)[:50]}")

        # --- Set value in JSON ---
        data, path_taken = _set_by_key_expr(data, key_expr, parsed_value)

        # --- Save: overwrite source file or write to output ---
        if source_path:
            save_path = source_path
        else:
            output_dir = os.path.join(task_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            save_path = os.path.join(output_dir, f"json_edit_{node_id}.json")

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"已修改 {'$'.join(path_taken)}，保存到 {os.path.basename(save_path)}")

        return {
            "artifacts": [os.path.relpath(save_path, task_dir)] if source_path else [f"output/json_edit_{node_id}.json"],
            "outputs": {"json": save_path},
        }
