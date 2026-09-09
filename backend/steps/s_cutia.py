"""s_cutia: 推送到剪辑台。

链路定位：素材编排已由上游「剪辑项目初始化」完成，本节点不再编排素材。
职责：
1. 接收上游剪辑项目 JSON 并推送到剪辑工作台（恢复为剪辑仓库当前项目）；
2. 打「待剪辑」标记（editor/push_state.json，供剪辑台首页待剪辑项目标签读取，
   首页展示目前暂未实现，数据已就绪）；
3. 发起系统提醒通知（前端头部通知中心轮询 /api/notifications 拉取展示）；
4. 按卡片设置的等待时长等待（默认 600 秒，支持取消）；
5. 等待结束后透传输出剪辑项目 JSON。
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from backend.control_plane.runtime import TaskCancelledError
from backend.editor.repository import EditorProjectRepository
from backend.steps.base_step import BaseStep
from backend.utils.runtime_notifications import push_notification


class S_Cutia(BaseStep):
    step_id = "cutia"
    step_name = "推送到剪辑台"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 输出为剪辑链共享文件 output/editing_project.json：
        # 共享文件无法作为本节点完成标记（上游节点也会写它），统一返回 False，
        # 由引擎按 DB 中记录的本节点 outputs 判定是否已完成。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def _mark_pending_edit(self, task_dir: str, task_id: str) -> None:
        """写入「待剪辑」推送标记，供剪辑台首页待剪辑项目标签读取。"""
        editor_dir = Path(task_dir) / "editor"
        editor_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "taskId": task_id,
            "pendingEdit": True,
            "pushedAt": datetime.now(timezone.utc).isoformat(),
        }
        with open(editor_dir / "push_state.json", "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        task_id = os.path.basename(os.path.normpath(task_dir))
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}
        repository = EditorProjectRepository()

        # 1. 接收上游剪辑项目 JSON 并推送到剪辑台（恢复为剪辑仓库当前项目）
        if callback:
            callback(15, "正在接收剪辑项目")
        project_input = str(inputs.get("project") or "")
        if project_input and os.path.isfile(project_input):
            with open(project_input, "r", encoding="utf-8") as handle:
                snapshot = repository.restore_snapshot(task_id, json.load(handle), updated_by="cutia_push")
        else:
            try:
                snapshot = repository.snapshot(task_id)
            except Exception as exc:
                raise ValueError("推送到剪辑台需要上游「剪辑项目」JSON 输入") from exc

        # 2. 打「待剪辑」标记（剪辑台首页标签数据源）
        self._mark_pending_edit(task_dir, task_id)

        # 3. 发起系统提醒通知
        push_notification(
            "info",
            "剪辑项目已推送到剪辑台",
            f"任务 {task_id} 的剪辑项目已就绪，请前往剪辑工作台处理",
            task_id=task_id,
            link=f"/editing?task={task_id}",
        )
        if callback:
            callback(35, "剪辑项目已推送到剪辑台，已发送系统提醒")

        # 4. 等待剪辑（卡片设置的等待时长，默认 600 秒）
        try:
            wait_seconds = max(float(config.get("wait_seconds") or 600), 0.0)
        except (TypeError, ValueError):
            wait_seconds = 600.0
        if wait_seconds > 0:
            waited = 0.0
            while waited < wait_seconds:
                chunk = min(2.0, wait_seconds - waited)
                time.sleep(chunk)
                waited += chunk
                if cancel_callback is not None and cancel_callback():
                    raise TaskCancelledError("等待剪辑被取消")
                if callback and int(waited) % 30 == 0:
                    percent = 40 + int(50 * waited / wait_seconds)
                    callback(percent, f"等待剪辑中 {int(waited)}/{int(wait_seconds)} 秒")

        # 5. 透传输出剪辑项目 JSON
        if callback:
            callback(95, "等待结束，透传输出剪辑项目")
        output_dir = Path(task_dir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        # 透传写回剪辑链共享项目文件（与输入同一个文件，保持 JSON 名称一致）
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
            callback(100, "剪辑项目已透传输出")
        return {
            "artifacts": [str(path)],
            "outputs": {"project": str(path)},
        }
