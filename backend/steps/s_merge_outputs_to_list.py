# -*- coding: utf-8 -*-
"""
输出合并为列表节点（Step）

作用：将多个上游节点的输出信息（文本或路径）合并为「列表格式」的 JSON 数据，
在内存中直接输出（不落盘），供下游节点消费。

输入：动态端口 输入1、输入2 …（any 类型，数量由前端 inputCount 控制）。
输出：json —— 形如
    {
      "items": [
        {"id": "输入1", "value": "<路径或字符串>", "type": "path|string|json"},
        {"id": "输入2", "value": "...", "type": "..."}
      ]
    }
其中 type 指示该条目值是文件路径还是普通文本/内联数据。
"""
import os

from backend.steps.base_step import BaseStep


class StepMergeOutputsToList(BaseStep):
    step_id = "s_merge_outputs_to_list"
    step_name = "输出合并为列表"
    dependencies = []

    def _collect(self) -> list:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        in_keys = sorted(
            [k for k in step_inputs if isinstance(k, str) and k.startswith("input_")],
            key=lambda x: int(x.split("_", 1)[1]),
        )
        items = []
        for k in in_keys:
            idx = int(k.split("_", 1)[1])
            val = step_inputs[k]
            item = {"id": f"输入{idx}"}
            if isinstance(val, str) and (
                os.path.isabs(val) and os.path.isfile(val)
                or os.path.isfile(os.path.join(getattr(self, "_task_dir", ""), val))
            ):
                item["value"] = val
                item["type"] = "path"
            else:
                item["value"] = val
                item["type"] = "json" if isinstance(val, (dict, list)) else "string"
            items.append(item)
        return items

    def check_artifact(self, task_dir: str) -> bool:
        # 本节点不落盘，产物即内存 JSON（outputs 非空即视为完成）。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        return any(isinstance(k, str) and k.startswith("input_") for k in step_inputs)

    def run(self, task_dir, callback=None, cancel_callback=None):
        self._task_dir = task_dir
        items = self._collect()
        data = {"items": items}
        if callback:
            try:
                callback(100, f"已合并 {len(items)} 项")
            except Exception:
                pass
        # 不落盘：直接以内联 JSON 作为输出，在节点间内存传递。
        return {"outputs": {"json": data}}
