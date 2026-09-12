"""s_text_concat: 文本拼接节点。

三个可选对象（输入1 / 输入2 / 输入框文本）按卡片设定的先后顺序拼接，中间用指定连接符相连：

    卡片配置：order_1 / order_2 / order_3  取值 input1 | input2 | custom
             separator                    取值 newline | space | custom
             custom_separator             separator=custom 时的连接符

输入值可以是纯文本，也可以是上游产出的文本文件路径（与「文本编辑」节点一致：
是存在的文件则读取内容，否则按原文处理）。空片段自动跳过，避免出现多余连接符。
"""
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

_ORDER_KEYS = ("order_1", "order_2", "order_3")
_ORDER_VALUES = {"input1", "input2", "custom"}


class S_TextConcat(BaseStep):
    step_id = "text_concat"
    step_name = "文本拼接"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return False  # 纯计算节点，每次执行都重新拼接

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    @staticmethod
    def _read_value(task_dir: str, value) -> str:
        """输入值 → 文本：存在的文件路径读内容，否则按原文（None → 空串）。"""
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return S_TextConcat._read_value(task_dir, value[0] if value else "")
        if not isinstance(value, str):
            return str(value)
        raw = value.strip()
        if not raw:
            return ""
        p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:  # noqa: BLE001
                return raw
        return value

    @staticmethod
    def _separator(config: dict) -> str:
        kind = str(config.get("separator") or "newline")
        if kind == "space":
            return " "
        if kind == "custom":
            return str(config.get("custom_separator") or "")
        return "\n"

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        pool = {
            "input1": self._read_value(task_dir, step_inputs.get("input1")),
            "input2": self._read_value(task_dir, step_inputs.get("input2")),
            "custom": str(config.get("custom_text") or ""),
        }

        order = []
        for key in _ORDER_KEYS:
            val = str(config.get(key) or "").strip()
            if val in _ORDER_VALUES:
                order.append(val)
        if not order:
            order = ["input1", "input2", "custom"]

        sep = self._separator(config)
        parts = [pool[k] for k in order if pool.get(k)]
        result = sep.join(parts)

        if callback:
            callback(60, f"拼接 {len(parts)} 段文本")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"text_concat_{node_id}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result)

        rel = f"output/text_concat_{node_id}.txt"
        if callback:
            callback(100, f"拼接完成（{len(result)} 字）")
        return {"artifacts": [rel], "outputs": {"text": rel}}
