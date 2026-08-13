import os
import json
import uuid
import time
import shutil
from typing import Optional, List, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.workflow_validation import normalize_workflow
TASKS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tasks")

router = APIRouter()

WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "workflows"
)
os.makedirs(WORKFLOWS_DIR, exist_ok=True)

# 工作流分组数据文件（与 workflow 定义分离的独立索引表）
WORKFLOW_GROUPS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "workflow_groups.json"
)


def _load_groups_data() -> dict:
    """读取分组数据：{"groups":[{id,name,order}], "membership":{wf_id:group_id|null}}"""
    if not os.path.exists(WORKFLOW_GROUPS_FILE):
        return {"groups": [], "membership": {}}
    try:
        with open(WORKFLOW_GROUPS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "groups": data.get("groups", []),
            "membership": data.get("membership", {}),
        }
    except (OSError, json.JSONDecodeError):
        return {"groups": [], "membership": {}}


def _save_groups_data(data: dict) -> None:
    os.makedirs(os.path.dirname(WORKFLOW_GROUPS_FILE), exist_ok=True)
    with open(WORKFLOW_GROUPS_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _group_id_of(wf_id: str) -> str | None:
    """查询某工作流所属分组 id（缺省视为未分组 None）。"""
    data = _load_groups_data()
    gid = data.get("membership", {}).get(wf_id)
    # 校验分组仍存在，否则视为未分组
    if gid and any(g.get("id") == gid for g in data.get("groups", [])):
        return gid
    return None


def _load_stored_workflow_meta(wf_id: str) -> dict:
    """从已保存的工作流定义回填 name/description/type 等元信息。

    执行接口（/execute、/execute-node）前端只发送 nodes/edges，未携带 name/description，
    导致任务文件夹下的 workflow.json 丢失这些字段、后台日志显示“未命名工作流”。
    这里从 config/workflows/{wf_id}.json 读取已保存的定义，缺省时回填，避免日志无名称。
    """
    fp = os.path.join(WORKFLOWS_DIR, f"{wf_id}.json")
    if not os.path.exists(fp):
        return {}
    try:
        with open(fp, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "type": data.get("type", ""),
            "createdAt": data.get("createdAt", ""),
        }
    except (OSError, json.JSONDecodeError):
        return {}


def _apply_workflow_meta(wf_id: str, req_name: str, req_desc: str) -> dict:
    """合并 name/description：优先使用请求体传入值，否则从已保存定义回填。"""
    meta = _load_stored_workflow_meta(wf_id)
    return {
        "name": req_name or meta.get("name", ""),
        "description": req_desc or meta.get("description", ""),
        "type": meta.get("type", ""),
        "createdAt": meta.get("createdAt", ""),
    }


def _build_workflow(wf_id: str, nodes: list, edges: list, req_name: str = "", req_desc: str = "") -> dict:
    """构造标准化 workflow（含元信息回填），供执行/节点执行/新建一般任务复用。"""
    meta = _apply_workflow_meta(wf_id, req_name, req_desc)
    workflow, _, _ = normalize_workflow({
        "id": wf_id,
        "name": meta["name"],
        "description": meta["description"],
        "type": meta["type"],
        "createdAt": meta["createdAt"],
        "nodes": nodes,
        "edges": edges,
    })
    return workflow


def _get_task_dir_for_workflow(wf_id: str) -> str:
    """获取全局工作流对应的固定任务目录"""
    task_dir = os.path.join(TASKS_ROOT, "flow_" + wf_id)
    return task_dir


def _ensure_task_dir_exists(wf_id: str) -> str:
    """确保工作流的任务目录存在，不存在则创建"""
    task_dir = _get_task_dir_for_workflow(wf_id)
    if not os.path.exists(task_dir):
        os.makedirs(os.path.join(task_dir, "cache"), exist_ok=True)
        os.makedirs(os.path.join(task_dir, "output"), exist_ok=True)
    return task_dir


def _find_latest_task_for_workflow(wf_id: str):
    latest_task = None
    latest_task_id = None
    latest_created_at = ""
    if not os.path.exists(TASKS_ROOT):
        return None, None

    for d in os.listdir(TASKS_ROOT):
        task_json = os.path.join(TASKS_ROOT, d, "task.json")
        if not os.path.exists(task_json):
            continue
        try:
            with open(task_json, "r", encoding="utf-8") as f:
                task = json.load(f)
            task_workflow_id = task.get("workflow_id", "")
            if not task_workflow_id:
                wf_json = os.path.join(TASKS_ROOT, d, "workflow.json")
                if os.path.exists(wf_json):
                    with open(wf_json, "r", encoding="utf-8") as wf:
                        wf_data = json.load(wf)
                    task_workflow_id = wf_data.get("id", "")
            if task_workflow_id != wf_id:
                continue
            created_at = task.get("created_at", "")
            if created_at >= latest_created_at:
                latest_created_at = created_at
                latest_task = task
                latest_task_id = d
        except Exception:
            continue
    return latest_task, latest_task_id


def _get_task_for_workflow(task_id: str, wf_id: str):
    task_json = os.path.join(TASKS_ROOT, task_id, "task.json")
    if not os.path.exists(task_json):
        return None

    try:
        with open(task_json, "r", encoding="utf-8") as f:
            task = json.load(f)
    except Exception:
        return None

    task_workflow_id = task.get("workflow_id", "")
    if not task_workflow_id:
        wf_json = os.path.join(TASKS_ROOT, task_id, "workflow.json")
        if os.path.exists(wf_json):
            try:
                with open(wf_json, "r", encoding="utf-8") as wf:
                    wf_data = json.load(wf)
                task_workflow_id = wf_data.get("id", "")
            except Exception:
                task_workflow_id = ""

    if task_workflow_id != wf_id:
        return None
    return task


class WorkflowSave(BaseModel):
    id: Optional[str] = None
    name: str = "Untitled Workflow"
    description: str = ""
    nodes: List[dict] = Field(default_factory=list)
    edges: List[dict] = Field(default_factory=list)
    type: str = "user"  # "user" or "task"


class WorkflowExecute(BaseModel):
    nodes: List[dict] = Field(default_factory=list)
    edges: List[dict] = Field(default_factory=list)
    input: dict = Field(default_factory=dict)
    # new=新建一般任务从头; debug=全局工作流调试写回固定任务; resume=断点; restart=全量重跑; restart_clean=从头(清cache)
    mode: str = Field(default="new")
    resume_from: Optional[str] = None  # node id to resume from
    task_id: str = ""
    name: str = ""  # 工作流名称（可选，缺省时从已保存的工作流定义回填）
    description: str = ""  # 工作流描述（可选，缺省时从已保存的工作流定义回填）

class NodeExecuteRequest(BaseModel):
    nodes: List[dict] = Field(default_factory=list)
    edges: List[dict] = Field(default_factory=list)
    input: dict = Field(default_factory=dict)
    node_id: str = ""  # specific node to execute
    task_id: str = ""  # direct task id（必须传，节点执行不跨任务边界新建）
    # node=仅本节点; downstream=本节点及其连线下游
    scope: str = Field(default="node")
    run_downstream: bool = False  # 兼容旧字段，True 等价于 scope="downstream"


class SpawnTaskRequest(BaseModel):
    """新建一般任务：把当前画布快照复制为任务私有 workflow。"""
    nodes: List[dict] = Field(default_factory=list)
    edges: List[dict] = Field(default_factory=list)
    input: dict = Field(default_factory=dict)


class DebugTaskRequest(BaseModel):
    """调试任务初始化：body 传画布快照，避免用 query 参数导致超长 URL（414）。"""
    nodes: List[dict] = Field(default_factory=list)
    edges: List[dict] = Field(default_factory=list)


def _list_files():
    files = []
    if not os.path.exists(WORKFLOWS_DIR):
        return files
    groups_data = _load_groups_data()
    membership = groups_data.get("membership", {})
    valid_group_ids = {g.get("id") for g in groups_data.get("groups", [])}
    for f in os.listdir(WORKFLOWS_DIR):
        if f.endswith(".json"):
            fp = os.path.join(WORKFLOWS_DIR, f)
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # Only include user workflows, skip task workflows
                if data.get("type") == "task":
                    continue
                nodes = data.get("nodes", [])
                wf_id = data.get("id", f.replace(".json", ""))
                # 统计节点类型分布，用于卡片悬停详情展示
                type_counts: dict = {}
                for n in nodes:
                    nt = (n.get("data") or {}).get("nodeType") or n.get("nodeType") or "unknown"
                    type_counts[nt] = type_counts.get(nt, 0) + 1
                # 解析分组归属（缺省/分组已删除 → 未分组 None）
                raw_gid = membership.get(wf_id)
                group_id = raw_gid if (raw_gid and raw_gid in valid_group_ids) else None
                files.append({
                    "id": wf_id,
                    "name": data.get("name", "Untitled"),
                    "description": data.get("description", ""),
                    "nodeCount": len(nodes),
                    "edgeCount": len(data.get("edges", [])),
                    "nodeTypes": type_counts,
                    "groupId": group_id,
                    "updatedAt": data.get("updatedAt", ""),
                })
            except Exception:
                pass
    return sorted(files, key=lambda x: x.get("updatedAt", ""), reverse=True)


@router.get("")
async def list_workflows():
    groups_data = _load_groups_data()
    return {
        "workflows": _list_files(),
        "groups": sorted(groups_data.get("groups", []), key=lambda g: g.get("order", 0)),
        "membership": groups_data.get("membership", {}),
    }


# ============ 工作流分组管理（静态路径须位于 /{wf_id} 参数化路由之前） ============
class GroupCreate(BaseModel):
    name: str


class MembershipUpdate(BaseModel):
    workflow_id: str
    group_id: Optional[str] = None  # None 表示移回未分组


@router.get("/groups")
async def list_groups():
    """返回分组列表与归属索引，供前端分组栏渲染。"""
    data = _load_groups_data()
    groups = sorted(data.get("groups", []), key=lambda g: g.get("order", 0))
    return {"groups": groups, "membership": data.get("membership", {})}


@router.post("/groups")
async def create_group(req: GroupCreate):
    """新建分组。"""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "分组名称不能为空")
    data = _load_groups_data()
    groups = data.get("groups", [])
    new_id = "grp_" + uuid.uuid4().hex[:8]
    max_order = max((g.get("order", 0) for g in groups), default=-1)
    groups.append({"id": new_id, "name": name, "order": max_order + 1})
    data["groups"] = groups
    _save_groups_data(data)
    return {"success": True, "group": groups[-1]}


@router.delete("/groups/{group_id}")
async def delete_group(group_id: str, action: str = "dissolve"):
    """删除分组。

    action=delete    ：连同组内工作流一起删除（含任务目录与绑定任务）
    action=dissolve ：仅解散分组，组内工作流移回未分组
    """
    if action not in ("delete", "dissolve"):
        raise HTTPException(400, "action 仅支持 delete / dissolve")
    data = _load_groups_data()
    groups = data.get("groups", [])
    membership = data.get("membership", {})
    target = next((g for g in groups if g.get("id") == group_id), None)
    if target is None:
        raise HTTPException(404, "分组不存在")

    member_wf_ids = [wid for wid, gid in membership.items() if gid == group_id]

    groups = [g for g in groups if g.get("id") != group_id]
    data["groups"] = groups

    if action == "dissolve":
        for wid in member_wf_ids:
            membership.pop(wid, None)
    else:
        for wid in member_wf_ids:
            membership.pop(wid, None)
            wf_fp = os.path.join(WORKFLOWS_DIR, f"{wid}.json")
            if os.path.exists(wf_fp):
                os.remove(wf_fp)
            task_dir = _get_task_dir_for_workflow(wid)
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
            from backend.control_plane.database import session_scope
            from backend.control_plane.models import Task
            from backend.control_plane.workflow_runtime import request_delete
            from sqlalchemy import select
            with session_scope() as session:
                bound_ids = [
                    t.id for t in session.scalars(select(Task)).all()
                    if ((t.payload or {}).get("workflow") or {}).get("id") == wid
                ]
            for task_id in bound_ids:
                request_delete(task_id, "workflow_deleted")

    data["membership"] = membership
    _save_groups_data(data)
    return {"success": True, "action": action, "deleted_workflows": len(member_wf_ids) if action == "delete" else 0}


@router.put("/groups/membership")
async def update_membership(req: MembershipUpdate):
    """调整单个工作流的分组归属（移动到指定分组 / 移回未分组）。"""
    wid = (req.workflow_id or "").strip()
    if not wid:
        raise HTTPException(400, "workflow_id 不能为空")
    data = _load_groups_data()
    groups = data.get("groups", [])
    membership = data.get("membership", {})
    if req.group_id is not None and not any(g.get("id") == req.group_id for g in groups):
        raise HTTPException(404, "目标分组不存在")
    if req.group_id is None:
        membership.pop(wid, None)
    else:
        membership[wid] = req.group_id
    data["membership"] = membership
    _save_groups_data(data)
    return {"success": True, "workflow_id": wid, "group_id": req.group_id}


@router.get("/{wf_id}")
async def get_workflow(wf_id: str):
    fp = os.path.join(WORKFLOWS_DIR, f"{wf_id}.json")
    if not os.path.exists(fp):
        raise HTTPException(404, "Workflow not found")
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
    data, migrated, removed = normalize_workflow(data)
    if migrated or removed:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return {"workflow": data, "removed_edges": removed}


@router.post("")
async def save_workflow(req: WorkflowSave):
    wf_id = req.id or uuid.uuid4().hex[:12]
    data, _, _ = normalize_workflow({
        "id": wf_id,
        "name": req.name,
        "description": req.description,
        "nodes": req.nodes,
        "edges": req.edges,
        "type": req.type,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    fp = os.path.join(WORKFLOWS_DIR, f"{wf_id}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"success": True, "id": wf_id}


@router.put("/{wf_id}")
async def update_workflow(wf_id: str, req: WorkflowSave):
    fp = os.path.join(WORKFLOWS_DIR, f"{wf_id}.json")
    old = {}
    if os.path.exists(fp):
        with open(fp, "r", encoding="utf-8") as f:
            old = json.load(f)
    data, _, _ = normalize_workflow({
        "id": wf_id,
        "name": req.name,
        "description": req.description,
        "nodes": req.nodes,
        "edges": req.edges,
        "type": req.type or old.get("type", ""),
        "createdAt": old.get("createdAt", time.strftime("%Y-%m-%dT%H:%M:%S")),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"success": True}


@router.delete("/{wf_id}")
async def delete_workflow(wf_id: str):
    fp = os.path.join(WORKFLOWS_DIR, f"{wf_id}.json")
    if os.path.exists(fp):
        os.remove(fp)
    # 同步删除 flow_<id> 任务文件夹
    task_dir = _get_task_dir_for_workflow(wf_id)
    if os.path.exists(task_dir):
        shutil.rmtree(task_dir, ignore_errors=True)
    # 级联删除所有绑定该工作流的任务（固定调试任务 + 一般任务 + 批量子任务）：
    # DB 记录标记 deleted + 任务工作区文件夹一并移除，避免磁盘占用。
    # 运行中/停止中任务按 request_delete 语义跳过（不误删，可稍后停止再删）。
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task
    from backend.control_plane.workflow_runtime import request_delete
    from sqlalchemy import select
    with session_scope() as session:
        bound_ids = [
            t.id for t in session.scalars(select(Task)).all()
            if ((t.payload or {}).get("workflow") or {}).get("id") == wf_id
        ]
    for task_id in bound_ids:
        request_delete(task_id, "workflow_deleted")
    return {"success": True, "deleted_tasks": len(bound_ids)}


@router.post("/{wf_id}/execute")
async def execute_workflow(wf_id: str, req: WorkflowExecute):
    from backend.control_plane.workflow_runtime import (
        submit_workflow, _find_workflow_task, _find_debug_task,
        _workspace, _clear_workspace_cache,
    )
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task
    workflow = _build_workflow(wf_id, req.nodes, req.edges, req.name, req.description)
    mode = req.mode or "new"
    task_id = req.task_id or None
    idempotency_scope = None
    with session_scope() as session:
        if mode == "new":
            # 新建一般任务执行：创建 detached 一般任务并投递。
            # 全局工作流的固定调试任务（is_debug）不受影响、保持绑定。
            task_id = None
            idempotency_scope = f"workflow-new:{wf_id}:{uuid.uuid4().hex[:8]}"
        elif mode == "debug":
            # 全局工作流调试：固定到 wf_id 的固定调试任务（无则自动创建 is_debug 任务）
            debug_task = _find_debug_task(session, wf_id)
            if debug_task is not None:
                task_id = debug_task.id
        else:
            # resume/restart/restart_clean：固定到当前任务（调试任务或一般任务）；
            # task_id 为空时落到固定调试任务
            if task_id:
                existing_task = session.get(Task, task_id)
                if existing_task is None or existing_task.status == "deleted" or ((existing_task.payload or {}).get("workflow") or {}).get("id") != wf_id:
                    task_id = None
            if not task_id:
                debug_task = _find_debug_task(session, wf_id)
                if debug_task is not None:
                    task_id = debug_task.id
                else:
                    bound = _find_workflow_task(session, wf_id)
                    if bound is not None:
                        task_id = bound.id
    # 执行前产物清理：restart_clean（从头执行）清空 cache 全新开始
    if mode == "restart_clean" and task_id:
        _clear_workspace_cache(_workspace(task_id))
    try:
        task, created = submit_workflow(workflow, req.input, mode=mode, resume_from=req.resume_from, task_id=task_id, idempotency_scope=idempotency_scope)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"success": True, "task_id": task.id, "created": created, "status": task.status}

@router.post("/{wf_id}/execute-node")
async def execute_single_node_api(wf_id: str, req: NodeExecuteRequest):
    from backend.control_plane.workflow_runtime import (
        submit_workflow, _resume_reset_set,
        _workspace, _clear_nodes_artifacts,
    )
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task
    workflow = _build_workflow(wf_id, req.nodes, req.edges)
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", []) or []
    # 节点执行必须限定在当前任务边界内，绝不新建任务
    with session_scope() as session:
        if not req.task_id:
            raise HTTPException(400, "节点执行必须指定任务（task_id），不允许跨任务新建")
        existing_task = session.get(Task, req.task_id)
        if existing_task is None or existing_task.status == "deleted":
            raise HTTPException(400, "任务不存在或已删除，无法执行节点")
        payload = existing_task.payload or {}
        if (payload.get("workflow") or {}).get("id") != wf_id:
            raise HTTPException(400, "任务与工作流不匹配，无法执行节点")
        task_id = existing_task.id
    # 节点级产物清理：node=仅本节点；downstream=本节点及其连线下游
    scope = req.scope or ("downstream" if req.run_downstream else "node")
    if scope == "downstream":
        node_ids = [n.get("id", "") for n in nodes]
        clear_set = _resume_reset_set(node_ids, edges, req.node_id) or {req.node_id}
        clear_ids = list(clear_set)
        exec_kwargs = {"resume_from": req.node_id}
    else:
        # 单节点执行：仅清空/执行该节点。始终提交完整工作流，用 exec_only 收窄执行范围，
        # 不裁剪节点，避免覆盖任务私有 workflow 导致历史加载画布只剩该节点。
        clear_ids = [req.node_id]
        exec_kwargs = {"exec_only": [req.node_id]}
    if task_id:
        _clear_nodes_artifacts(task_id, clear_ids, _workspace(task_id))
    try:
        task, created = submit_workflow(workflow, req.input, mode="resume", task_id=task_id, **exec_kwargs)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"success": True, "task_id": task.id, "node_id": req.node_id, "run_downstream": scope == "downstream", "created": created, "status": task.status}


@router.get("/{wf_id}/debug-task")
async def get_debug_task(wf_id: str, nodes: str = "", edges: str = ""):
    """返回（无则创建）全局工作流 wf_id 绑定的固定调试任务 id。

    前端点击工作流加载画布时调用，用于接管/初始化固定调试任务，避免每次新建。
    可选传 nodes/edges（JSON 字符串）以便用当前画布快照初始化调试任务。
    """
    from backend.control_plane.workflow_runtime import submit_workflow, _find_debug_task
    from backend.control_plane.database import session_scope
    nodes_list: list = []
    edges_list: list = []
    if nodes:
        try:
            nodes_list = json.loads(nodes)
        except json.JSONDecodeError:
            nodes_list = []
    if edges:
        try:
            edges_list = json.loads(edges)
        except json.JSONDecodeError:
            edges_list = []
    workflow = _build_workflow(wf_id, nodes_list, edges_list)
    with session_scope() as session:
        debug_task = _find_debug_task(session, wf_id)
        if debug_task is not None:
            return {"task_id": debug_task.id, "created": False}
    # 无固定调试任务：用当前画布快照初始化一个专用调试任务（仅绑定，不执行）
    task, created = submit_workflow(workflow, {}, mode="debug_init", enqueue=False)
    return {"task_id": task.id, "created": created}


@router.post("/{wf_id}/debug-task")
async def create_debug_task(wf_id: str, req: DebugTaskRequest):
    """返回（无则创建）全局工作流 wf_id 绑定的固定调试任务 id（POST 版）。

    画布快照通过 JSON body 传递（大工作流避免超长 URL）；已存在调试任务时直接返回。
    """
    from backend.control_plane.workflow_runtime import submit_workflow, _find_debug_task
    from backend.control_plane.database import session_scope
    workflow = _build_workflow(wf_id, req.nodes, req.edges)
    with session_scope() as session:
        debug_task = _find_debug_task(session, wf_id)
        if debug_task is not None:
            return {"task_id": debug_task.id, "created": False}
    task, created = submit_workflow(workflow, {}, mode="debug_init", enqueue=False)
    return {"task_id": task.id, "created": created}


@router.post("/{wf_id}/spawn-task")
async def spawn_task(wf_id: str, req: SpawnTaskRequest):
    """新建一般任务：把当前画布快照复制为任务私有 workflow（detached），不投递执行。

    返回 task_id，前端进入一般任务编辑态；之后画布上的执行/保存都只作用于该私有副本。
    """
    from backend.control_plane.workflow_runtime import submit_workflow
    workflow = _build_workflow(wf_id, req.nodes, req.edges)
    task, created = submit_workflow(workflow, req.input, mode="spawn", enqueue=False)
    return {"success": True, "task_id": task.id, "created": created, "status": task.status}


@router.post("/{wf_id}/save-as-global")
async def save_as_global(wf_id: str, req: WorkflowSave):
    """一般任务「另存为全局」：把画布快照写入一个新的全局工作流定义文件。"""
    new_id = uuid.uuid4().hex[:12]
    data, _, _ = normalize_workflow({
        "id": new_id,
        "name": req.name or req.description or "另存工作流",
        "description": req.description,
        "nodes": req.nodes,
        "edges": req.edges,
        "type": "user",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    fp = os.path.join(WORKFLOWS_DIR, f"{new_id}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"success": True, "id": new_id}

@router.get("/{wf_id}/status")
async def workflow_status(wf_id: str):
    from backend.control_plane.database import session_scope
    from backend.control_plane.workflow_runtime import _find_workflow_task, _legacy_node_state
    with session_scope() as session:
        task = _find_workflow_task(session, wf_id)
        if task is None:
            return {"task": None}
        return {"task": {
            "id": task.id,
            "status": task.status,
            "cancel_reason": task.cancel_reason,
            "error_class": task.error_class,
            "retry_count": task.retry_count,
            "nodes": {node.node_key: _legacy_node_state(node) for node in task.nodes},
        }}


