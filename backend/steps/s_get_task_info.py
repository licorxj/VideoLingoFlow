"""s_get_task_info: 获取任务信息节点。

从 task.json（以及输入节点的 workflow 配置）读取任务元信息，并以文本形式输出给下游节点：
  - task_name        任务名称
  - input_language   输入语言
  - output_language  输出语言
  - var1             变量1
  - var2             变量2

所有取值均来自「输入节点」的配置（最终落到 task.json 的 input 段）与 task.json 顶层 task_name，
数据以内存方式传递给下游，不落盘。
"""
import json
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


class S_GetTaskInfo(BaseStep):
    step_id = "get_task_info"
    step_name = "获取任务信息"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        # 取值节点不产出文件，始终视为成功
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        task_json_path = os.path.join(task_dir, "task.json")
        workflow_path = os.path.join(task_dir, "workflow.json")

        task_name = ""
        input_cfg: dict = {}

        if os.path.exists(task_json_path):
            try:
                with open(task_json_path, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                task_name = task_data.get("task_name", "") or ""
                input_cfg = task_data.get("input", {}) or {}
            except Exception as e:
                print(f"[GetTaskInfo] 读取 task.json 失败: {e}")

        # 兜底：task.json 的 input 段缺少某些字段时，从输入节点配置补全
        missing_keys = [k for k in ("source_language", "target_language", "var1", "var2")
                        if not input_cfg.get(k)]
        if missing_keys and os.path.exists(workflow_path):
            try:
                with open(workflow_path, "r", encoding="utf-8") as f:
                    wf = json.load(f)
                for node in wf.get("nodes", []):
                    if node.get("data", {}).get("nodeType") == "input":
                        cfg = node.get("data", {}).get("config", {}) or {}
                        for k in missing_keys:
                            if cfg.get(k):
                                input_cfg[k] = cfg[k]
                        break
            except Exception as e:
                print(f"[GetTaskInfo] 读取 workflow.json 输入节点失败: {e}")

        input_language = input_cfg.get("source_language", "") or ""
        output_language = input_cfg.get("target_language", "") or ""
        var1 = input_cfg.get("var1", "") or ""
        var2 = input_cfg.get("var2", "") or ""

        if callback:
            callback(100, f"已获取任务信息: name={task_name or '-'}, "
                           f"in_lang={input_language or '-'}, out_lang={output_language or '-'}, "
                           f"var1={var1 or '-'}, var2={var2 or '-'}")

        return {
            "artifacts": [],
            "outputs": {
                "task_name": task_name,
                "input_language": input_language,
                "output_language": output_language,
                "var1": var1,
                "var2": var2,
            },
        }
