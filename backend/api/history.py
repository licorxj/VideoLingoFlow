"""History API: query completed/failed tasks."""
import os
import json
from typing import Optional

from fastapi import APIRouter

from backend.control_plane.database import session_scope
from backend.control_plane.models import Task

router = APIRouter()

WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "workflows",
)

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted"}


def _workflow_name(workflow_id: str) -> Optional[str]:
    """Resolve workflow display name from config/workflows/{id}.json, None if unavailable."""
    if not workflow_id:
        return None
    fp = os.path.join(WORKFLOWS_DIR, f"{workflow_id}.json")
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f).get("name")
    except Exception:
        return None


def _task_type(task: dict) -> str:
    """Classify task: batch (has batch_id), workflow (has workflow_id), otherwise normal.

    已解除工作流绑定的调试任务（detached）按一般任务显示。
    """
    if task["batch_id"]:
        return "batch"
    if task.get("detached"):
        return "normal"
    if task["workflow_id"]:
        return "workflow"
    return "normal"


def _history_task(task: Task) -> dict:
    payload = task.payload or {}
    batch = payload.get("batch") or {}
    workflow = payload.get("workflow") or {}
    workflow_id = workflow.get("id") or payload.get("workflow_id") or batch.get("workflow_id") or ""
    batch_id = batch.get("batch_id") or payload.get("batch_id")
    status = "completed" if task.status == "succeeded" else task.status
    result = {
        "id": task.id,
        "task_name": batch.get("task_name") or payload.get("task_name") or (task.project.name if task.project else None),
        "workflow_id": workflow_id,
        "workflow_name": batch.get("workflow_name") or workflow.get("name") or _workflow_name(workflow_id),
        "status": status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.updated_at.isoformat() if task.status in TERMINAL_STATUSES and task.updated_at else None,
        "batch_id": batch_id,
        "detached": bool(payload.get("detached")),
    }
    result["task_type"] = _task_type(result)
    return result


@router.get("")
async def list_history(status: Optional[str] = None):
    with session_scope() as session:
        tasks = [_history_task(task) for task in session.query(Task).order_by(Task.created_at.desc()).all()]
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    else:
        tasks = [t for t in tasks if t.get("status") in ("completed", "failed")]
    return {"tasks": tasks}
