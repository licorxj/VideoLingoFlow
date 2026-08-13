"""s_json_to_text: Convert JSON to text file, with optional key expression extraction."""
import json
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


def _resolve_path(value, task_dir: str = "") -> str:
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


def _extract_by_key_expr(data, key_expr: str):
    """Extract value from nested dict using '$'-separated key expression.

    e.g. "a$b$c" -> data["a"]["b"]["c"]
    """
    keys = [k.strip() for k in key_expr.split("$") if k.strip()]
    current = data
    for key in keys:
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
    return current


class S_JsonToText(BaseStep):
    step_id = "s_json_to_text"
    step_name = "JSON转文本"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        path = os.path.join(task_dir, "output", f"json2text_{node_id}.txt")
        return os.path.exists(path)

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        mode = node_config.get("mode", "full")
        if isinstance(mode, list):
            mode = mode[0] if mode else "full"
        key_expr = node_config.get("key_expr", "").strip()

        # Resolve JSON input
        json_input = step_inputs.get("json", "")
        if not json_input:
            raise ValueError("未连接 JSON 输入。")

        json_path = _resolve_path(json_input, task_dir)
        if json_path:
            data = _read_json(json_path)
        elif isinstance(json_input, str):
            try:
                data = json.loads(json_input)
            except json.JSONDecodeError:
                raise ValueError(f"输入既不是有效文件路径，也不是合法 JSON 字符串: {json_input[:100]}")
        else:
            data = json_input  # already a dict/list

        if callback:
            callback(30, f"模式: {'全量转文本' if mode == 'full' else 'key取值'}")

        # Process based on mode
        if mode == "full":
            if isinstance(data, (dict, list)):
                text = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                text = str(data)
        else:
            # key expression mode
            if not key_expr:
                raise ValueError("key取值模式下未设置 key 表达式。")
            value = _extract_by_key_expr(data, key_expr)
            if isinstance(value, (dict, list)):
                text = json.dumps(value, ensure_ascii=False, indent=2)
            else:
                text = str(value) if value is not None else ""

        # Write to output file
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"json2text_{node_id}.txt"
        output_path = os.path.join(output_dir, output_filename)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)

        if callback:
            callback(100, f"已生成 {output_filename} ({len(text)} 字符)")

        return {
            "artifacts": [f"output/{output_filename}"],
            "outputs": {
                "text": output_path,
            },
        }
