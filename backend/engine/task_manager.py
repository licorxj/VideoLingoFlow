"""
Task manager: orchestrates task creation, execution, rollback, and status tracking.
"""
from typing import Callable, Optional

from backend.control_plane.database import session_scope
from backend.control_plane.models import Task


class TaskManager:
    """Manages the full lifecycle of video processing tasks."""

    def create_task(
        self,
        task_type: str,
        input_files: dict,
        name: str = "",
        options: dict = None,
        ws_callback: Callable = None,
    ) -> dict:
        raise RuntimeError("旧任务创建已移除，请使用控制平面工作流提交")

    def execute_task(self, task_id: str, from_step: str = None, ws_callback: Callable = None) -> dict:
        raise RuntimeError("旧任务执行已移除，请使用控制平面工作流提交")

    def rollback_to_step(self, task_id: str, step_id: str) -> dict:
        raise RuntimeError("旧任务回滚已移除，请使用控制平面检查点恢复")

    def get_task(self, task_id: str) -> Optional[dict]:
        with session_scope() as session:
            task = session.get(Task, task_id)
            return {"id": task.id, "status": task.status} if task else None

    def list_tasks(self, status: str = None) -> list:
        with session_scope() as session:
            tasks = [{"id": task.id, "status": task.status, "created_at": task.created_at.isoformat() if task.created_at else None} for task in session.query(Task).all()]
        return [task for task in tasks if not status or task["status"] == status]

    def delete_task(self, task_id: str) -> bool:
        from backend.control_plane.workflow_runtime import request_delete
        return request_delete(task_id) is not None


# Singleton
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
