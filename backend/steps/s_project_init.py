"""s_project_init: 收集上游素材并构造初始剪辑JSON。

作为「剪辑 JSON 接力」链路的起点：把上游各素材端口的文件注册进剪辑仓库，
生成默认时间线骨架与素材清单，导出为初始剪辑项目 JSON，
供下游「Cutia 交互剪辑」恢复后整理筛选，再交「剪辑AI Agent」二次精选。
"""
import json
import os
from pathlib import Path
from typing import Callable, Optional

from backend.editor.repository import EditorProjectRepository
from backend.steps.base_step import BaseStep


class S_ProjectInit(BaseStep):
    step_id = "project_init"
    step_name = "剪辑项目初始化"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 输出为剪辑链共享文件 output/editing_project.json：
        # 共享文件无法作为本节点完成标记（上游节点也会写它），统一返回 False，
        # 由引擎按 DB 中记录的本节点 outputs 判定是否已完成。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def _input_candidate_ids(self, task_id: str, task_dir: str) -> list[str]:
        """把上游连线素材文件映射为仓库导入候选 ID（与 S_Cutia 同规则）。"""
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

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        task_id = os.path.basename(os.path.normpath(task_dir))
        config = getattr(self, "_node_config", {}) or {}
        arrange_tracks = bool(config.get("arrange_tracks", True))
        if callback:
            callback(15, "正在重新初始化剪辑项目")
        repository = EditorProjectRepository()
        # 1) 删除剪辑链共享 JSON，本次执行彻底重新初始化
        shared_path = Path(task_dir) / "output" / "editing_project.json"
        shared_path.unlink(missing_ok=True)
        # 2) 重置仓库当前剪辑项目，使导入时重建默认时间线编排
        repository.reset_project(task_id)
        if callback:
            callback(30, "正在收集上游素材")
        candidate_ids = self._input_candidate_ids(task_id, task_dir)
        # 注册素材并构造默认项目：arrange_tracks 开启时预排主轨视频/封面/音频/字幕/标题轨
        snapshot = repository.import_assets(task_id, candidate_ids, arrange_tracks=arrange_tracks)
        if callback:
            callback(70, "正在导出初始剪辑项目 JSON")
        output_dir = Path(task_dir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        # 剪辑链共享项目文件：链上所有节点读写同一个文件，保持 JSON 名称一致
        path = output_dir / "editing_project.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "taskId": task_id,
                    "revision": snapshot.get("revision"),
                    "project": snapshot.get("project"),
                    "assets": snapshot.get("assets"),
                    "lastWriter": str(getattr(self, "_node_id", "") or ""),
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        if callback:
            callback(100, "初始剪辑项目已生成")
        return {
            "artifacts": [str(path)],
            "outputs": {"project": str(path)},
        }
