"""s_set_task_info: 写入任务信息节点（「获取任务信息」的逆向操作）。

用上游传入的值更新任务元信息，最终落到 task.json：
  - task_name        任务名称          → task.json.task_name
  - input_language   输入语言          → task.json.input.source_language
  - output_language  输出语言          → task.json.input.target_language
  - var1             变量1             → task.json.input.var1
  - var2             变量2             → task.json.input.var2

普通节点执行结束后，运行时会把 task.json 的 input / task_name 同步回任务负载，
因此下游节点与「获取任务信息」都能读到新值。

节点本身不产出文件（artifacts 为空），仅在内存中回传执行完成情况。
"""
import json
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

# (输入端口 id, task.json 写入位置, 人类可读名)
# target_key == "task_name" 表示写 task.json 顶层，其余写入 input 段
_FIELD_MAP = (
    ("task_name", "task_name", "任务名称"),
    ("input_language", "source_language", "输入语言"),
    ("output_language", "target_language", "输出语言"),
    ("var1", "var1", "变量1"),
    ("var2", "var2", "变量2"),
)


class S_SetTaskInfo(BaseStep):
    step_id = "set_task_info"
    step_name = "写入任务信息"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        # 写入节点不产出文件，始终视为成功
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    @staticmethod
    def _pick(step_inputs: dict, key: str) -> str:
        """取输入值：兼容多连线聚合成的列表与各类标量，统一转为去空白字符串。"""
        raw = step_inputs.get(key)
        if isinstance(raw, (list, tuple)):
            raw = next((v for v in raw if v not in (None, "", [], {})), "")
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw.strip()
        return str(raw).strip()

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        task_json_path = os.path.join(task_dir, "task.json")

        values = {port: self._pick(step_inputs, port) for port, _, _ in _FIELD_MAP}

        if callback:
            callback(20, "写入任务信息...")

        task_data: dict = {}
        if os.path.exists(task_json_path):
            try:
                with open(task_json_path, "r", encoding="utf-8") as f:
                    task_data = json.load(f) or {}
            except Exception as e:  # noqa: BLE001 - 损坏时按空任务重建，不阻断写入
                print(f"[SetTaskInfo] 读取 task.json 失败，将重建: {e}")
                task_data = {}
        if not isinstance(task_data, dict):
            task_data = {}

        input_cfg = task_data.get("input")
        if not isinstance(input_cfg, dict):
            input_cfg = {}

        updated: dict = {}
        skipped: list = []
        for port, target_key, label in _FIELD_MAP:
            value = values.get(port) or ""
            if not value:
                # 空输入表示「不改动该项」，避免把已有信息清空
                skipped.append(label)
                continue
            if target_key == "task_name":
                task_data["task_name"] = value
            else:
                input_cfg[target_key] = value
            updated[label] = value

        task_data["input"] = input_cfg

        try:
            os.makedirs(task_dir, exist_ok=True)
            with open(task_json_path, "w", encoding="utf-8") as f:
                json.dump(task_data, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"写入任务信息失败: 无法写入 task.json: {e}")

        message = (
            f"已更新任务信息: {', '.join(updated)}" if updated
            else "没有可写入的任务信息（所有输入均为空）"
        )
        if skipped:
            message += f"；跳过空值: {', '.join(skipped)}"
        print(f"[SetTaskInfo] {message}")

        if callback:
            callback(100, message)

        return {
            "artifacts": [],
            "outputs": {
                "result": {
                    "success": bool(updated),
                    "message": message,
                    "updated": updated,
                    "skipped": skipped,
                },
            },
        }
