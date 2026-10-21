"""AI 创作「生产驾驶舱」执行接口。

把矩阵里的一个格子（章节 × 生产阶段）翻译成一次节点执行：
按 ``(creation_id, step_id, chapter_id|shot_id)`` **代客组装一个最小工作流**，
投递给既有的控制平面（``submit_workflow``），因此不需要用户回到画布、也不需要新建工作流。

执行引擎、资源令牌、子进程隔离、断点续跑全部复用；本模块只负责三件事：
  1) 组装节点配置（内置类型 defaultConfig + 本次覆盖值）；
  2) 投递并记录来源标记（写入 task payload.input，便于按项目回查）；
  3) 回查该项目近期驾驶舱任务的状态，供矩阵轮询。
"""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend import creation as agi

router = APIRouter(prefix="/api/creation", tags=["creation-tasks"])

# 驾驶舱合成工作流的固定 id（不落盘，仅作为任务归属标记）
COCKPIT_WF_ID = "creation-cockpit"
COCKPIT_SOURCE = "creation_cockpit"


class StageRunRequest(BaseModel):
    """执行一次「章节 × 阶段」生产。"""
    creation_id: str
    step_id: str
    chapter_id: str = ""
    chapter_ids: list = Field(default_factory=list)
    shot_id: str = ""
    force: bool = False
    extra_config: dict = Field(default_factory=dict)
    node_label: str = ""


def _node_type(step_id: str) -> dict:
    from backend.config.builtin_node_types import get_builtin_node_types

    for item in get_builtin_node_types():
        if item.get("id") == step_id:
            return item
    raise HTTPException(404, f"未知生产阶段节点: {step_id}")


def _build_node(req: StageRunRequest, node_type: dict) -> dict:
    """组装单节点：defaultConfig 打底 + 本次路由/开关覆盖。"""
    config = dict(node_type.get("defaultConfig") or {})
    config.update({
        "creation_id": req.creation_id,
        "chapter_id": req.chapter_id or "",
        "shot_id": req.shot_id or "",
    })
    if req.chapter_ids:
        config["chapter_ids"] = list(req.chapter_ids)
    if "force" in config or req.force:
        config["force"] = bool(req.force)
    # 节点未声明 force 字段时（如纯 LLM 节点）不注入，避免无意义配置
    if not req.force and "force" not in (node_type.get("defaultConfig") or {}):
        config.pop("force", None)
    for key, value in (req.extra_config or {}).items():
        config[key] = value
    return {
        "id": f"cockpit_{req.step_id}_{uuid.uuid4().hex[:8]}",
        "type": "workflow",
        "position": {"x": 0, "y": 0},
        "data": {
            "nodeType": req.step_id,
            "label": req.node_label or node_type.get("name") or req.step_id,
            "config": config,
            "execution_domain": node_type.get("execution_domain") or "process",
        },
    }


@router.post("/run-stage")
def run_stage(req: StageRunRequest):
    """投递一次「章节 × 阶段」生产任务，返回 task_id 供前端轮询。"""
    try:
        agi.get_creation(req.creation_id)
    except agi.NotFoundError:
        raise HTTPException(404, f"创作项目不存在: {req.creation_id}")
    node_type = _node_type(req.step_id)
    if not req.chapter_id and not req.chapter_ids and not req.shot_id:
        raise HTTPException(400, "请指定 chapter_id / chapter_ids / shot_id 之一")

    from backend.control_plane.workflow_runtime import submit_workflow

    workflow = {
        "id": COCKPIT_WF_ID,
        "name": "创作驾驶舱",
        "description": f"{node_type.get('name') or req.step_id} · 单节点生产",
        "type": "cockpit",
        "nodes": [_build_node(req, node_type)],
        "edges": [],
    }
    # 来源标记写进 input（workflow 会被 normalize，避免放 workflow 层被裁剪）
    input_config = {
        COCKPIT_SOURCE: True,
        "creation_id": req.creation_id,
        "step_id": req.step_id,
        "chapter_id": req.chapter_id or "",
        "chapter_ids": list(req.chapter_ids or []),
        "shot_id": req.shot_id or "",
        "force": bool(req.force),
    }
    # 幂等 scope 必须确定性：同键非终态任务会命中 submit_workflow 的单飞保护
    # （workflow_runtime.submit_workflow 1185-1195）直接返回已有任务，避免驾驶舱
    # 同一格子被连点/重复提交出多个并发任务互相抢资源、双跑双登记资产。
    # 终态任务（成功/失败/取消）会走重建分支生成新一轮执行，不影响重跑。
    target = req.chapter_id or (",".join(sorted(req.chapter_ids)) if req.chapter_ids else "") or req.shot_id
    scope = f"cockpit:{req.creation_id}:{req.step_id}:{target}"
    try:
        task, created = submit_workflow(workflow, input_config, mode="new", idempotency_scope=scope)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return {
        "success": True,
        "task_id": task.id,
        # created=False 表示该格子已有非终态任务在途（单飞保护命中），前端据此提示而非静默新建
        "created": created,
        "status": task.status,
        "step_id": req.step_id,
        "chapter_id": req.chapter_id,
    }


def _fetch_cockpit_task_ids(creation_id: str) -> list[str] | None:
    """JSON 下推过滤本项目的任务 id（独立 session，失败可安全回退）。

    返回 None 表示下推不可用（如 SQLite 未编译 JSON1），调用方回退到全量扫描。
    """
    from sqlalchemy import func, select

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task

    try:
        with session_scope() as session:
            stmt = (
                select(Task.id)
                .where(func.json_extract(Task.payload, "$.input.creation_id") == creation_id)
                .order_by(Task.created_at.desc())
                .limit(500)
            )
            return list(session.scalars(stmt).all())
    except Exception:
        return None


@router.get("/tasks")
def list_cockpit_tasks(creation_id: str = "", limit: int = 200):
    """列出驾驶舱发起的任务（可按项目过滤），供矩阵格子显示进行中/失败。"""
    from sqlalchemy import select

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task, TaskNode

    # 优先按 creation_id 下推过滤：避免「扫描全局最近 500 条」在系统繁忙时
    # 把本项目任务挤出窗口，导致前端误判无活动任务、停止轮询、矩阵停在旧进度。
    allowed_ids: set[str] | None = None
    if creation_id:
        pushed = _fetch_cockpit_task_ids(creation_id)
        if pushed is not None:
            allowed_ids = set(pushed)
    with session_scope() as session:
        stmt = select(Task).order_by(Task.created_at.desc()).limit(500)
        rows = session.scalars(stmt).all()
        out = []
        for task in rows:
            if allowed_ids is not None and task.id not in allowed_ids:
                continue
            payload = task.payload or {}
            meta = payload.get("input") or {}
            if not meta.get(COCKPIT_SOURCE):
                continue
            if creation_id and meta.get("creation_id") != creation_id:
                continue
            node = session.scalars(
                select(TaskNode).where(TaskNode.task_id == task.id)
            ).first()
            node_payload = (node.payload if node else None) or {}
            out.append({
                "task_id": task.id,
                "creation_id": meta.get("creation_id") or "",
                "step_id": meta.get("step_id") or "",
                "chapter_id": meta.get("chapter_id") or "",
                "shot_id": meta.get("shot_id") or "",
                "status": task.status,
                "node_status": node.status if node else "",
                "error_class": (node.error_class if node else "") or task.error_class or "",
                # 进度/等待文案：供前端区分「排队中」与「进行中」（等待资源时有 wait_message）
                "progress": node_payload.get("progress", 0),
                "wait_message": node_payload.get("wait_message", ""),
                "created_at": str(task.created_at or ""),
                "updated_at": str(task.updated_at or ""),
            })
            if len(out) >= limit:
                break
    return {"tasks": out}


@router.post("/tasks/{task_id}/cancel")
def cancel_cockpit_task(task_id: str):
    """取消一个驾驶舱任务。

    必须走 request_cancel（置 stopping + 杀子进程树 + 协作式取消），
    不能用 request_delete——后者对 running/stopping 是静默 no-op
    （workflow_runtime.request_delete 1371-1373），会让前端拿到
    success 但任务照跑。返回真实结果状态供前端展示。
    """
    from backend.control_plane.workflow_runtime import request_cancel

    task = request_cancel(task_id, "user_requested")
    if task is None:
        raise HTTPException(404, f"任务不存在: {task_id}")
    status = task.status
    if status in {"succeeded", "failed", "cancelled", "deleted"}:
        result = "already_finished"
    elif status == "stopping":
        result = "stopping"
    else:
        result = "cancelled"
    return {"success": True, "task_id": task_id, "result": result, "status": status}
