"""s_json_get: Extract a value from an input JSON by key expression.

The extracted value is returned directly in the node outputs (any type) and is
NOT written to disk — data flows in-memory to downstream nodes.
"""
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
    """Extract value from nested dict/list using '$'-separated key expression.

    e.g. "a$b$c" -> data["a"]["b"]["c"]; array indices are integers.
    Mirrors the extraction approach used by the JSON编辑 node.
    """
    keys = [k.strip() for k in key_expr.split("$") if k.strip()]
    if not keys:
        raise ValueError("key表达式为空")

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


class S_JsonGet(BaseStep):
    step_id = "s_json_get"
    step_name = "JSON取值"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 取值节点不产出文件，始终视为成功
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        output_count = int(node_config.get("outputCount", 1) or 1)
        key_exprs_raw = node_config.get("key_exprs", [])
        if isinstance(key_exprs_raw, str):
            try:
                key_exprs_raw = json.loads(key_exprs_raw)
            except Exception:
                key_exprs_raw = [key_exprs_raw]
        # 确保长度与输出端口数对齐
        while len(key_exprs_raw) < output_count:
            key_exprs_raw.append("")
        key_exprs = [str(k or "").strip() for k in key_exprs_raw[:output_count]]

        if not any(key_exprs):
            raise ValueError("未设置任何取值表达式，请在节点配置中填写（如 images$0）")

        # --- Resolve JSON input ---
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
            callback(40, f"已读取 JSON，准备按 {len([k for k in key_exprs if k])} 个表达式取值")

        # --- Extract values for each output port ---
        outputs = {}
        for i, expr in enumerate(key_exprs):
            port_key = f"out_{i + 1}"
            if not expr:
                outputs[port_key] = ""
                continue
            try:
                value = _extract_by_key_expr(data, expr)
                outputs[port_key] = value
                if callback:
                    preview = value if isinstance(value, (str, int, float, bool)) else json.dumps(value, ensure_ascii=False)
                    callback(50 + int(40 * (i + 1) / max(len(key_exprs), 1)), f"取值{i+1} ({expr}): {str(preview)[:60]}")
            except Exception as e:
                outputs[port_key] = ""
                print(f"[JsonGet] Warning: 表达式 '{expr}' 取值失败: {e}")

        if callback:
            callback(100, f"完成: {len([v for v in outputs.values() if v != ''])}/{len(outputs)} 个端口有值")

        # 不落盘：直接返回取值，由下游按 any 类型接入
        return {
            "artifacts": [],
            "outputs": outputs,
        }
