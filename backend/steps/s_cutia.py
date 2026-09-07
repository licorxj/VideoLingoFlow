import json
import os
from pathlib import Path
from typing import Callable, Optional

from backend.editor.repository import EditorProjectRepository
from backend.control_plane.runtime import WorkflowWaitingError
from backend.steps.base_step import BaseStep


class S_Cutia(BaseStep):
    step_id = "cutia"
    step_name = "Cutia 交互剪辑"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return bool(self._latest_export(task_dir))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def _latest_export(self, task_dir: str) -> str:
        task_id = os.path.basename(os.path.normpath(task_dir))
        repository = EditorProjectRepository()
        try:
            assets = repository.snapshot(task_id)["assets"]
        except Exception:
            return ""
        exports = [
            asset for asset in assets
            if asset.get("source") == "editor_export" and asset.get("type") == "video"
        ]
        for asset in reversed(exports):
            path = Path(task_dir) / str(asset.get("relative_path") or "")
            if path.is_file():
                return str(path)
        return ""

    def _input_candidate_ids(self, task_id: str, task_dir: str) -> list[str]:
        repository = EditorProjectRepository()
        inputs = getattr(self, "_step_inputs", {}) or {}
        root = Path(task_dir).resolve()
        input_paths = set()
        for value in inputs.values():
            if not isinstance(value, str) or not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                path = root / path
            try:
                input_paths.add(path.resolve())
            except OSError:
                continue
        return [
            candidate.id
            for candidate in repository.import_candidates(task_id)
            if (root / candidate.relative_path).resolve() in input_paths
        ]

    def _write_project_snapshot(self, task_dir: str, task_id: str) -> str:
        """导出当前剪辑项目快照，供下游节点接收剪辑项目 JSON。"""
        repository = EditorProjectRepository()
        try:
            snapshot = repository.snapshot(task_id)
        except Exception:
            return ""
        output_dir = Path(task_dir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        node_id = getattr(self, "_node_id", "") or "project"
        path = output_dir / f"cutia_project_{node_id}.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "taskId": task_id,
                    "revision": snapshot.get("revision"),
                    "project": snapshot.get("project"),
                    "assets": snapshot.get("assets"),
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        return str(path)

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        task_id = os.path.basename(os.path.normpath(task_dir))
        export_path = self._latest_export(task_dir)
        if export_path:
            project_path = self._write_project_snapshot(task_dir, task_id)
            if callback:
                callback(100, "已取得 Cutia 导出成片")
            outputs = {"video": export_path}
            if project_path:
                outputs["project"] = project_path
            return {"outputs": outputs, "artifacts": [export_path]}

        candidate_ids = self._input_candidate_ids(task_id, task_dir)
        if callback:
            callback(30, "正在准备 Cutia 项目素材")
        EditorProjectRepository().import_assets(task_id, candidate_ids)
        if callback:
            callback(50, "等待在 Cutia 中编辑并导出")
        raise WorkflowWaitingError(
            "等待在 Cutia 剪辑工作台导出成片",
            f"/editing?task={task_id}",
        )
