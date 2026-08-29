# -*- coding: utf-8 -*-
"""
文本输入框节点（Step）

作用：提供一个文本输入框，将其内容作为「文本」输出给下游节点。
输出的文本在内存中传递（不落盘），不依赖任何上游产物。

输入：可选 any（接入时忽略，输出始终为用户输入的文本）。
输出：text —— 节点配置中的文本字符串。
"""
from backend.steps.base_step import BaseStep


class StepTextInput(BaseStep):
    step_id = "s_text_input"
    step_name = "文本输入框"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 本节点不落盘，内存输出即视为完成。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}
        text = (node_config.get("text", "") or "").strip()
        if callback:
            try:
                callback(100, f"已输出文本（{len(text)} 字）")
            except Exception:
                pass
        # 不落盘：直接以内联文本作为输出，在节点间内存传递。
        return {"outputs": {"text": text}}
