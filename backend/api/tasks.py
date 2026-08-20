"""Tasks API: query task status, artifacts, and task lifecycle actions."""
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()


SUNSET = "2026-09-30T00:00:00Z"
TASK_STATUS_MAP = {"succeeded": "completed"}
NODE_STATUS_MAP = {"succeeded": "completed"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted"}


def _deprecated(payload: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        payload,
        status_code=status_code,
        headers={
            "Deprecation": "true",
            "Sunset": SUNSET,
            "Link": "</api/workflows>; rel=\"successor-version\"",
        },
    )


def _node_workbench_url(node) -> str:
    """从节点 payload 提取 workbench_url（result 优先，其次 data.config），找不到返回空串。"""
    payload = node.payload or {}
    result = payload.get("result", {}) or {}
    if isinstance(result, dict):
        url = result.get("workbench_url", "") or ""
        if url:
            return str(url)
    config = ((payload.get("data", {}) or {}).get("config", {}) or {})
    return str(config.get("workbench_url", "") or config.get("workbenchUrl", "") or "")


def _task_node_state(node) -> dict:
    """构造节点级响应（与 workflow_runtime._legacy_node_state 一致，并补充 workbench_url）。

    outputs 仅为 result.outputs 端口映射（result 存在 outputs 键时），不回传整个 result 字典。
    """
    payload = node.payload or {}
    data = payload.get("data", {}) or {}
    result = payload.get("result", {}) or {}
    if isinstance(result, dict) and "outputs" in result:
        outputs = result.get("outputs", {}) or {}
    else:
        outputs = {}
    # error 字段：failed 时优先返回真实错误信息（payload.message），回退错误分类（error_class）
    node_error = (payload.get("message") or node.error_class or "") if node.status == "failed" else (node.error_class or "")
    return {
        "nodeType": data.get("nodeType", ""),
        "label": data.get("label", data.get("nodeType", "")),
        "status": NODE_STATUS_MAP.get(node.status, node.status),
        "progress": 100 if node.status == "succeeded" else 0,
        "message": "Completed" if node.status == "succeeded" else (payload.get("message", "") if node.status == "failed" else ""),
        "outputs": outputs if isinstance(outputs, dict) else {},
        "error": node_error,
        "error_class": node.error_class or "",
        "workbench_url": _node_workbench_url(node),
    }


def _task_payload(task) -> dict:
    """构造旧版任务/节点响应结构（与 workflow_runtime._legacy_task_data 对齐并补齐字段）。"""
    payload = task.payload or {}
    batch = payload.get("batch", {}) or {}
    workflow = payload.get("workflow", {}) or {}
    return {
        "id": task.id,
        "status": TASK_STATUS_MAP.get(task.status, task.status),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.updated_at.isoformat() if task.status in TERMINAL_STATUSES and task.updated_at else None,
        "is_batch": bool(batch.get("batch_id")),
        "is_debug": bool(payload.get("is_debug")),
        "detached": bool(payload.get("detached")),
        "input": payload.get("input", {}) or {},
        "edges": workflow.get("edges", []) or [],
        "nodes": {node.node_key: _task_node_state(node) for node in task.nodes},
        "workflow": workflow,
    }


def _load_task(task_id: str):
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task
    from backend.workflow_validation import normalize_workflow

    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            return None
        workflow, _, _ = normalize_workflow((task.payload or {}).get("workflow", {}))
        if workflow != (task.payload or {}).get("workflow", {}):
            task.payload = {**(task.payload or {}), "workflow": workflow}
        payload = _task_payload(task)
        payload["workflow"] = workflow
        return payload


class WorkflowUpdateRequest(BaseModel):
    """Request body for updating a task's workflow."""
    class Config:
        extra = "allow"


class CreateTaskRequest(BaseModel):
    task_type: str
    input_files: dict = {}
    name: str = ""
    options: dict = {}


class ExecuteTaskRequest(BaseModel):
    from_step: Optional[str] = None


@router.get("/meta/types")
async def task_meta_types():
    """可用节点类型元数据（id/label/分类），必须定义在 /{task_id} 之前。"""
    from backend.config.builtin_node_types import get_builtin_node_types

    types = [
        {"id": node["id"], "label": node.get("name", node["id"]), "category": node.get("category", "")}
        for node in get_builtin_node_types()
    ]
    return _deprecated({"types": types})


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = _load_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return _deprecated({"task": task})


@router.get("/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    task = _load_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return _deprecated({"cache": [], "output": [], "task_id": task["id"]})


@router.get("")
async def list_tasks(status: Optional[str] = None):
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task

    with session_scope() as session:
        query = session.query(Task).order_by(Task.created_at.desc())
        if status:
            mapped = {value: key for key, value in TASK_STATUS_MAP.items()}.get(status, status)
            query = query.filter(Task.status == mapped)
        tasks = [_task_payload(task) for task in query.all()]
    return _deprecated({"tasks": tasks})


@router.post("")
async def create_task(req: CreateTaskRequest):
    """在控制平面创建一条 Task 记录（status=created，payload 含 workflow/input），不执行。"""
    from backend.control_plane.workflow_runtime import submit_workflow

    workflow = {
        "id": req.task_type,
        "name": req.name or req.task_type,
        "nodes": [
            {
                "id": "input",
                "data": {"nodeType": "input", "label": "输入", "config": req.options or {}},
            }
        ],
        "edges": [],
    }
    task, _created = submit_workflow(workflow, req.input_files or {}, mode="new", enqueue=False)
    return _deprecated({"success": True, "task_id": task.id})


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    from backend.control_plane.workflow_runtime import request_delete
    task = request_delete(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if task.status in {"running", "stopping"}:
        raise HTTPException(409, "任务正在执行或停止中，请先停止后再删除")
    return _deprecated({"success": True, "task_id": task_id, "status": task.status, "waiting": False})


@router.get("/{task_id}/workflow")
async def get_task_workflow(task_id: str):
    task = _load_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return _deprecated({"workflow": task["workflow"]})


@router.put("/{task_id}/workflow")
async def update_task_workflow(task_id: str, req: WorkflowUpdateRequest):
    from pathlib import Path
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task
    from backend.control_plane.workflow_runtime import _write_legacy_task
    from backend.workflow_validation import normalize_workflow

    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "Task not found")
        values = req.model_dump()
        current = (task.payload or {}).get("workflow", {}) or {}
        workflow, _, _ = normalize_workflow({
            "id": values.get("id") or current.get("id", ""),
            "name": values.get("name", current.get("name", "")),
            "description": values.get("description", current.get("description", "")),
            "nodes": values.get("nodes", []),
            "edges": values.get("edges", []),
        })
        task.payload = {**(task.payload or {}), "workflow": workflow}
        session.flush()
        root = Path(os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", Path.cwd() / "control_plane_workspaces"))
        workspace = root / task.id
        if workspace.exists():
            # 任务内保存：同步更新任务文件夹私有 workflow.json（与全局工作流解耦）
            (workspace / "workflow.json").write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
            _write_legacy_task(task, workspace)
    return _deprecated({"success": True, "task_id": task_id, "workflow": workflow})


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, reason: str = "user_requested"):
    """Request cancellation for a running task.
    If the task is actively running, set a cancel flag for the scheduler.
    If the task is NOT running (e.g. interrupted), directly reset running nodes to pending."""
    from backend.control_plane.workflow_runtime import request_cancel

    task = request_cancel(task_id, reason)
    if task is not None:
        return _deprecated({"success": True, "task_id": task_id, "status": task.status, "cancel_reason": task.cancel_reason})
    raise HTTPException(404, "Task not found")


@router.post("/{task_id}/pause")
async def pause_task(task_id: str):
    from backend.control_plane.workflow_runtime import request_pause

    task = request_pause(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return _deprecated({"success": True, "task_id": task_id, "status": task.status})


@router.post("/{task_id}/execute")
async def execute_task(task_id: str, req: Optional[ExecuteTaskRequest] = None):
    """对已创建任务执行：from_step 存在时 mode=resume，否则 mode=new。"""
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task
    from backend.control_plane.workflow_runtime import submit_workflow

    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "Task not found")
        payload = task.payload or {}
        workflow = payload.get("workflow") or {}
        input_config = payload.get("input") or {}
    from_step = (req.from_step if req else None) or None
    mode = "resume" if from_step else "new"
    task, _created = submit_workflow(workflow, input_config, mode=mode, resume_from=from_step, task_id=task_id)
    return _deprecated({"success": True, "task_id": task_id, "status": task.status})


@router.post("/{task_id}/rollback/{step_id}")
async def rollback_task(task_id: str, step_id: str):
    """将 step_id 之后（含）节点重置为 pending、任务重置为 queued 并重新投递 Celery。"""
    from backend.control_plane.celery_runtime import celery_app
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task
    from backend.control_plane.runtime import queue_for
    from backend.control_plane.workflow_runtime import _resume_reset_set

    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "Task not found")
        workflow = (task.payload or {}).get("workflow", {}) or {}
        node_ids = [node.get("id", "") for node in workflow.get("nodes", [])]
        if step_id not in node_ids:
            raise HTTPException(404, f"Step not found: {step_id}")
        reset_set = _resume_reset_set(node_ids, workflow.get("edges", []) or [], step_id) or {step_id}
        for node in task.nodes:
            if node.node_key not in reset_set:
                continue
            node.status = "pending"
            node.worker_id = None
            node.cancel_reason = None
            node.error_class = None
            node.checkpoint_key = None
            if node.payload:
                node.payload = {**node.payload, "result": {}}
        task.status = "queued"
        task.worker_id = None
        task.cancel_reason = None
        task.error_class = None
        task.deletion_requested = False
        task.version += 1
        session.flush()
        if celery_app is None:
            raise HTTPException(503, "Celery 不可用")
        celery_app.send_task("videolingo.workflow.execute", args=[task_id], queue=queue_for("io"))
    return _deprecated({"success": True, "task_id": task_id, "status": "queued"})


class OpenFileRequest(BaseModel):
    file_path: str
    task_id: str | None = None


def _open_candidates(file_path: str, root: Path, legacy_root: Path, task_id: str | None = None):
    """生成候选路径：带任务 ID 时只在对应工作区解析相对路径。"""
    p = Path(file_path)
    if p.is_absolute():
        yield p
        return
    if task_id:
        task_path = Path(task_id)
        if task_path.is_absolute() or task_path.name != task_id or task_id in {".", ".."}:
            return
        for base in (root / task_id, legacy_root / task_id):
            yield base / p
        return
    for base in (root, legacy_root):
        if not base.exists():
            continue
        for child in base.iterdir():
            yield child / p
        yield base / p


@router.post("/open-file")
async def open_file(req: OpenFileRequest):
    """打开任务产物文件/目录（兼容绝对路径与相对工作区路径，含路径穿越防护）。"""
    root = Path(os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", Path.cwd() / "control_plane_workspaces"))
    legacy_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "tasks"
    allowed_bases = [b.resolve() for b in (root, legacy_root)]
    if req.task_id:
        allowed_bases = [(base / req.task_id).resolve() for base in (root, legacy_root)]
    for cand in _open_candidates(req.file_path, root, legacy_root, req.task_id):
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        if not any(resolved.is_relative_to(base) for base in allowed_bases):
            continue
        if resolved.exists():
            os.startfile(str(resolved))
            return _deprecated({"success": True})
    raise HTTPException(404, "File not found")
