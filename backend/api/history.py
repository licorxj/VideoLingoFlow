"""History API: 任务历史列表（含进行中任务，排除已删除/已归档）。"""
import os
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.control_plane.database import session_scope
from backend.control_plane.models import Task

router = APIRouter()

WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "workflows",
)

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted", "archived"}

# 历史项目列表「不显示」的状态：已删除 / 删除中断残留（历史遗留的 stuck deleting 记录）、
# 已归档（产物已挪到外部目录，另有「加载已归档项目」入口）。
# 其余状态一律显示 —— 进行中的一般任务（待执行/排队中/执行中/暂停/等待继续/停止中）
# 必须能从历史项目页点进画布继续操作，否则没有其它入口能看到并操作它们。
HISTORY_HIDDEN_STATUSES = {"deleted", "deleting", "archived"}


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
        # 批次归档信息：供「历史项目 → 已归档项目」载回使用
        "archived": task.status == "archived",
        "archive_path": getattr(task, "archive_path", None),
        "archived_at": task.archived_at.isoformat() if getattr(task, "archived_at", None) else None,
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
        tasks = [t for t in tasks if t.get("status") not in HISTORY_HIDDEN_STATUSES]
    return {"tasks": tasks}


class RestoreArchivedRequest(BaseModel):
    task_ids: List[str] = []


@router.get("/archived")
async def list_archived():
    """列出全部已归档项目，供「加载已归档项目」弹窗选择。"""
    from backend.engine.batch_archive import list_archived_tasks

    return {"tasks": list_archived_tasks()}


@router.post("/restore")
async def restore_archived(req: RestoreArchivedRequest):
    """载回已归档项目：以 task_id 新建工作区、复制归档内容、删除归档文件夹后刷新历史。"""
    from backend.engine.batch_archive import restore_archived_tasks

    if not req.task_ids:
        raise HTTPException(status_code=400, detail="请选择要载回的已归档项目")
    return restore_archived_tasks(req.task_ids)
