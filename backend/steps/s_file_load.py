# -*- coding: utf-8 -*-
"""
文件加载节点（Step）

作用：提供一个文件路径输入框 + 文件加载按钮（前端卡片交互），将所选文件
的绝对路径作为「文件路径」输出给下游节点。不拷贝、不生成新文件，仅输出路径。

输入：可选 any（接入时忽略，输出始终为配置中的文件路径）。
输出：filepath —— 文件的绝对路径字符串。
"""
import os

from backend.steps.base_step import BaseStep


class StepFileLoad(BaseStep):
    step_id = "s_file_load"
    step_name = "文件加载"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 本节点不落盘，内存输出即视为完成。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}
        raw = (node_config.get("filePath", "") or "").strip()
        abspath = os.path.abspath(raw) if raw else ""
        if callback:
            try:
                callback(100, f"已加载文件：{abspath}" if abspath else "未选择文件")
            except Exception:
                pass
        # 不落盘：直接以内联文件路径作为输出，在节点间内存传递。
        return {"outputs": {"filepath": abspath}}
