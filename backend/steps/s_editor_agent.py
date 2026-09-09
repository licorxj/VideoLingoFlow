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
        # 接力上游剪辑项目 JSON：先恢复为当前状态，再做二次精选。
        # 单节点重跑防叠加：共享文件若由本节点上次写回（lastWriter==本节点），
        # 则回退到进入本节点前的输入快照（cache），从进入点状态重新执行。
        node_id = getattr(self, "_node_id", "")
        project_input = str(inputs.get("project") or "")
        if project_input and os.path.isfile(project_input):
            with open(project_input, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            input_backup = os.path.join(task_dir, "cache", f"editing_input_{node_id}.json")
            if node_id and data.get("lastWriter") == node_id and os.path.isfile(input_backup):
                try:
                    with open(input_backup, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    pass
            elif node_id:
                os.makedirs(os.path.dirname(input_backup), exist_ok=True)

                with open(input_backup, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False)
            repository.restore_snapshot(task_id, data, updated_by="editor_agent")
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
            imagegen_iface_id=config.get("imagegen_iface_id") or None,
            imagegen_model=config.get("imagegen_model") or None,
            videogen_iface_id=config.get("videogen_iface_id") or None,
            videogen_model=config.get("videogen_model") or None,
        )
        if run.get("status") != "completed":
            raise RuntimeError(run.get("error") or "剪辑 AI Agent 执行失败")
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_id = getattr(self, "_node_id", "result")

        # 运行记录：工具调用轨迹，便于回溯 AI 的编辑过程
        artifacts_path = os.path.join(output_dir, f"editor_agent_{node_id}.json")
        with open(artifacts_path, "w", encoding="utf-8") as handle:
            json.dump(run, handle, ensure_ascii=False, indent=2)

        # 剪辑项目快照：写回剪辑链共享项目文件（含时间线、素材与修订号），
        # 供下游「剪辑渲染」等节点消费；链上所有节点共用同一 JSON 文件名
        latest = repository.snapshot(task_id)
        project_path = os.path.join(output_dir, "editing_project.json")
        with open(project_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "taskId": task_id,
                    "revision": latest.get("revision"),
                    "project": latest.get("project"),
                    "assets": latest.get("assets"),
                    "lastWriter": node_id,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )

        # 执行结果文本
        result_path = os.path.join(output_dir, f"editor_agent_result_{node_id}.txt")
        with open(result_path, "w", encoding="utf-8") as handle:
            handle.write(str(run.get("content") or "已完成项目分析和编辑。"))

        if callback:
            callback(100, "剪辑项目已更新")
        return {
            "artifacts": [artifacts_path, result_path],
            "outputs": {
                "project": project_path,
                "artifacts": artifacts_path,
                "result": result_path,
            },
        }
