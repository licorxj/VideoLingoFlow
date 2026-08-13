import json
import os
from typing import Callable, Optional

from backend.editor.agent.service import EditorAgentService
from backend.editor.repository import EditorProjectRepository
from backend.steps.base_step import BaseStep


class S_EditorAgent(BaseStep):
    step_id = "editor_agent"
    step_name = "剪辑AI Agent"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        return os.path.isfile(os.path.join(task_dir, "output", f"editor_agent_{node_id}.json"))

    def validate_inputs(self, task_dir: str) -> bool:
        config = getattr(self, "_node_config", {}) or {}
        return bool(config.get("instruction", "").strip())

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        task_id = os.path.basename(os.path.normpath(task_dir))
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}
        instruction = str(inputs.get("text") or config.get("instruction") or "").strip()
        if not instruction:
            raise ValueError("剪辑 AI Agent 需要编辑指令")
        if callback:
            callback(20, "正在加载剪辑项目和素材")
        repository = EditorProjectRepository()
        try:
            snapshot = repository.snapshot(task_id)
        except Exception:
            snapshot = repository.import_assets(task_id, [])
        if callback:
            callback(50, "AI Agent 正在执行时间线工具")
        run = EditorAgentService(repository).execute(
            task_id,
            instruction,
            str(config.get("expert_role") or "auto"),
            snapshot.get("revision"),
        )
        if run.get("status") != "completed":
            raise RuntimeError(run.get("error") or "剪辑 AI Agent 执行失败")
        output_path = os.path.join(task_dir, "output", f"editor_agent_{getattr(self, '_node_id', 'result')}.json")
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(run, handle, ensure_ascii=False, indent=2)
        if callback:
            callback(100, "剪辑项目已更新")
        return {
            "project": os.path.join(task_dir, "editor", "project.json"),
            "artifacts": output_path,
            "result": run.get("content", ""),
        }
