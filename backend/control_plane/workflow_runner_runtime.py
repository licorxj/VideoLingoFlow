"""工作流执行器（workflow_runner）节点的运行时执行器。

设计要点
--------
「工作流执行器」在画布上是一个**引用型容器节点**：它引用一个已存在的工作流定义
（``data.workflowRef``），在运行时把该工作流的 nodes/edges 展开成虚拟节点并逐层
执行，**把整个子工作流的执行当成父流程里的一个节点**。

与循环（loop）节点的关系
------------------------
两者机制同构（容器内跑子图 + 端口映射 + 分层并发），差异在于：

* loop：子图内联在 ``data.loopMeta.internalWorkflow``，按迭代次数重复执行 N 次，
  复用父 workspace；
* workflow_runner：子图来自外部工作流定义（快照或实时引用），只执行 1 次，
  默认在父 workspace 下新建**独立子目录**执行，避免与父流程文件互相污染。

本模块刻意**不复用 loop_runtime 的私有函数**（除公共的 workflow_runtime 工具），
保持 loop 的既有行为零改动；未来若需合并，可将虚拟节点增删 / 分层执行 / 注入
抽到公共 subgraph_runtime。

关键约定
--------
* 虚拟节点 key：``{runner_id}#0000__{内部节点 id}``
  - 与 loop 同构（``#`` 便于前端过滤、``__`` 使产物文件名带 ``_<node_id>`` 后缀，
    能被 ``_clear_nodes_artifacts`` 的兜底规则清理）；
  - 只执行一次，故 index 恒为 0。
* 虚拟节点行是**临时态**：执行成功后删除，保持 ``task.nodes`` 规模受控；
  **执行失败时保留**，便于在任务详情里定位子工作流内部是哪个节点失败。
* 子工作流的 ``input`` 节点**不交给 _run_node 执行**（那会读父任务的
  ``task.payload.input`` 造成串数据），而是由本模块直接产出：优先用输入映射值，
  回退该 input 节点自身的 config。
* 递归保护：创建虚拟节点时把祖先工作流 id 栈写入 ``config.__wfRunnerStack``，
  执行前检查深度与环。

目录隔离
--------
``workspaceMode="subdir"`` 时在 ``<父 workspace>/subwf_<node_id>/`` 下执行，
子图节点的 task_dir 即该目录（``_run_node`` 已接受 workspace 参数）。
终点节点的产物会按 ``promoteOutputs`` **提升**到父 workspace 的 ``cache/``
并带 ``_<runner_node_id>`` 后缀——否则下游节点按 ``find_artifact`` 在父 cache
里找不到子目录中的产物，链路会断。
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.control_plane.database import session_scope
from backend.control_plane.models import Task, TaskNode
from backend.control_plane.runtime import TaskCancelledError
from backend.control_plane.workflow_runtime import (
    _build_layers,
    _cancel_requested,
    _event,
    _node_type,
    _resolve_inputs_from,
    _resolve_step_inputs,
    _resource_for,
    _run_node,
    _write_legacy_task,
    queue_for,
    reset_legacy_input_override,
    set_legacy_input_override,
)
from backend.steps.step_registry import new_step_instance


# 递归调用深度上限（防止 A 调 B、B 调 A 的无限展开）
WF_RUNNER_MAX_DEPTH = int(os.getenv("WF_RUNNER_MAX_DEPTH", "3"))
# 子工作流内部层内并发上限
WF_RUNNER_MAX_CONCURRENCY = int(os.getenv("WF_RUNNER_MAX_CONCURRENCY", "8"))
# 自动输出模式下可填充的固定输出端口数量（out_1 ~ out_N）
_OUTPUT_PORT_COUNT = 4
# 调用栈在节点 config 中的隐藏字段名（前端不展示）
_STACK_KEY = "__wfRunnerStack"

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WORKFLOWS_DIR = os.path.join(_BACKEND_DIR, "config", "workflows")


# --------------------------------------------------------------------------- #
# 子工作流定义加载
# --------------------------------------------------------------------------- #
def _load_workflow_file(wf_id: str) -> dict:
    """按 id 读取工作流定义文件（backend/config/workflows/<id>.json）。"""
    safe_id = os.path.basename(str(wf_id or "").strip())
    if not safe_id or safe_id in (".", ".."):
        return {}
    path = os.path.join(_WORKFLOWS_DIR, f"{safe_id}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _subgraph_of(workflow: dict) -> tuple[list, list]:
    """取出并规范化子图：展开组合节点（group），返回 (nodes, edges)。"""
    nodes = workflow.get("nodes") or []
    edges = workflow.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return [], []
    try:
        from backend.workflow_validation import normalize_workflow

        normalized, _, _ = normalize_workflow(
            {"nodes": copy.deepcopy(nodes), "edges": copy.deepcopy(edges)}, expand_groups=True
        )
        return normalized.get("nodes") or [], normalized.get("edges") or []
    except Exception as exc:  # noqa: BLE001 - 规范化失败不阻断，退化为原始定义
        print(f"[wf_runner] 子工作流规范化失败，使用原始定义: {exc}", flush=True)
        return nodes, edges


def _resolve_subgraph(ref: dict, config: dict) -> tuple[list, list]:
    """按引用模式解析子图：snapshot 用快照，live 实时读取工作流文件。

    快照来源优先级：``data.workflowRef.snapshot`` → ``config.workflowSnapshot``
    （前端选择工作流后写入 config，便于在配置面板内直接落盘）→ 按 wf_id 实时读取。
    """
    mode = str(ref.get("mode") or config.get("refMode") or "snapshot")
    wf_id = str(ref.get("wfId") or config.get("targetWorkflowId") or "")
    if mode == "live":
        workflow = _load_workflow_file(wf_id)
        if not workflow:
            raise ValueError(f"未找到工作流定义: {wf_id}（实时引用模式）")
        return _subgraph_of(workflow)
    snapshot = ref.get("snapshot")
    if not isinstance(snapshot, dict) or not snapshot.get("nodes"):
        snapshot = config.get("workflowSnapshot")
    if not isinstance(snapshot, dict) or not snapshot.get("nodes"):
        # 快照缺失时回退实时读取，避免「配了快照但快照为空」直接失败
        if wf_id:
            workflow = _load_workflow_file(wf_id)
            if workflow:
                return _subgraph_of(workflow)
        raise ValueError("工作流执行器缺少子工作流快照，请重新选择目标工作流以生成快照")
    return _subgraph_of(snapshot)


# --------------------------------------------------------------------------- #
# 虚拟节点
# --------------------------------------------------------------------------- #
def _prefix_for(runner_node_id: str) -> str:
    return f"{runner_node_id}#0000__"


def _create_virtual_nodes(session, task_id: str, inner_nodes: list, prefix: str, stack: list) -> tuple[list, dict]:
    """为子图节点创建虚拟 TaskNode 行，返回（虚拟节点 id 列表，节点快照表）。"""
    nodes_by_id: dict[str, dict] = {}
    node_ids: list[str] = []
    for inner in inner_nodes:
        if not isinstance(inner, dict):
            continue
        inner_id = str(inner.get("id") or "")
        if not inner_id:
            continue
        snapshot = copy.deepcopy(inner)
        snapshot["id"] = f"{prefix}{inner_id}"
        snapshot["selected"] = False
        data = snapshot.get("data")
        if isinstance(data, dict):
            config = dict(data.get("config") or {})
            # 注入祖先调用栈，供嵌套的工作流执行器做递归保护
            config[_STACK_KEY] = list(stack)
            data["config"] = config
        node_id = snapshot["id"]
        nodes_by_id[node_id] = snapshot
        node_ids.append(node_id)
        resource = _resource_for(_node_type(snapshot))
        session.add(TaskNode(
            task_id=task_id,
            node_key=node_id,
            status="pending",
            resource_class=resource,
            queue=queue_for(resource),
            payload=snapshot,
        ))
    session.flush()
    return node_ids, nodes_by_id


def _delete_virtual_nodes(task_id: str, prefix: str) -> None:
    """删除本次执行的虚拟节点行，保持 task.nodes 规模受控。"""
    try:
        with session_scope() as session:
            rows = [
                row for row in session.scalars(select(TaskNode).where(TaskNode.task_id == task_id)).all()
                if row.node_key.startswith(prefix)
            ]
            for row in rows:
                session.delete(row)
            session.flush()
    except Exception as exc:  # noqa: BLE001 - 清理失败不影响主结果
        print(f"[wf_runner] 清理虚拟节点失败: {exc}", flush=True)


def _node_outputs(task_id: str, node_id: str) -> dict:
    with session_scope() as session:
        row = session.scalar(select(TaskNode).where(TaskNode.task_id == task_id, TaskNode.node_key == node_id))
        if row is None:
            return {}
        result = (row.payload or {}).get("result")
        outputs = result.get("outputs") if isinstance(result, dict) else None
        return outputs if isinstance(outputs, dict) else {}


def _mark_input_node_done(task_id: str, node_id: str, outputs: dict, workspace: Path) -> None:
    """把子工作流的 input 节点直接标记为完成并写入 outputs（不执行其 run）。"""
    with session_scope() as session:
        task = session.get(Task, task_id)
        node = session.scalar(select(TaskNode).where(TaskNode.task_id == task_id, TaskNode.node_key == node_id))
        if node is None:
            return
        node.status = "succeeded"
        node.payload = {**node.payload, "result": {"outputs": outputs}, "progress": 100, "message": ""}
        _event(session, task_id, "node_succeeded", {
            "node": node_id, "node_id": node_id, "step_id": node_id,
            "status": "succeeded", "progress": 100, "outputs": outputs,
        })
        if task is not None:
            _write_legacy_task(task, workspace)


def _input_fallback_outputs(node_payload: dict) -> dict:
    """input 节点未被映射时，回退其自身 config（而非父任务 input，避免串数据）。"""
    config = ((node_payload or {}).get("data") or {}).get("config") or {}
    outputs: dict[str, Any] = {}
    if config.get("url"):
        outputs["url"] = config["url"]
    for config_key, port in (("videoPath", "video"), ("audioPath", "audio"), ("subtitlePath", "subtitle")):
        if config.get(config_key):
            outputs[port] = config[config_key]
    return outputs


# 子工作流 input 节点的数据类字段：由「输入映射」负责传入，设置项覆盖里忽略这些 key
_INPUT_DATA_FIELD_KEYS = (
    "selectedTypes", "videoPath", "audioPath", "subtitlePath", "url", "filePath",
)

# 输入节点端口 → input 节点 config key：用于把注入值回填进 workspace/task.json 的 input
_PORT_TO_INPUT_CONFIG_KEY = {
    "video": "videoPath",
    "audio": "audioPath",
    "subtitle": "subtitlePath",
    "url": "url",
}


def _apply_input_config_overrides(inner_nodes: list, overrides: dict) -> list:
    """把「工作流执行器」节点上填写的 inputConfigs 合并进子工作流 input 节点的 config。

    子工作流的 input 节点既有数据类字段（videoPath/audioPath/...），也有设置项
    （source_language / target_language / var1 / var2 / copyInputs ...）。允许在父节点
    统一覆盖，避免子工作流只能吃自己文件里保存的旧值。
    留空（None/""）表示沿用子工作流原始配置。
    """
    if not isinstance(overrides, dict) or not overrides:
        return inner_nodes
    patched: list = []
    for node in inner_nodes or []:
        if not isinstance(node, dict) or _node_type(node) != "input":
            patched.append(node)
            continue
        override = overrides.get(str(node.get("id") or ""))
        if not isinstance(override, dict) or not override:
            patched.append(node)
            continue
        item = dict(node)
        data = dict(item.get("data") or {})
        node_config = dict(data.get("config") or {})
        for key, value in override.items():
            if key in _INPUT_DATA_FIELD_KEYS:
                continue  # 数据输入由「输入映射」负责
            if value is None or value == "":
                continue
            node_config[key] = value
        data["config"] = node_config
        item["data"] = data
        patched.append(item)
    return patched


def _inner_input_config(inner_nodes: list) -> dict:
    """取子工作流 input 节点的 config（已合并父节点覆盖值）。

    该 dict 会作为 ``input_config`` 传给 ``_resolve_inputs_from``，由其向下游节点注入
    source_language / target_language / var1 / var2 等设置项。
    """
    for node in inner_nodes or []:
        if isinstance(node, dict) and _node_type(node) == "input":
            return dict(((node.get("data") or {}).get("config")) or {})
    return {}


# --------------------------------------------------------------------------- #
# 端口映射
# --------------------------------------------------------------------------- #
def _build_injections(mappings: list, outer_inputs: dict, prefix: str, nodes_by_id: dict | None = None) -> dict:
    """构造输入注入：{虚拟节点 id: {端口: 值}}。

    ``outer_inputs`` 为本节点对外端口（in_1..in_N）实际收到的上游值。

    传入 ``nodes_by_id`` 时会校验目标节点类型：输入桥接只允许注入子工作流的 input 节点。
    注入其他节点会绕过连线强行改写它的输入，造成上下游依赖错乱，因此直接忽略。
    """
    injections: dict[str, dict] = {}
    for mapping in mappings or []:
        if not isinstance(mapping, dict):
            continue
        exposed = str(mapping.get("exposedPortId") or "")
        target_node = str(mapping.get("targetNodeId") or "")
        target_port = str(mapping.get("targetPortId") or "")
        if not exposed or not target_node or not target_port:
            continue
        if nodes_by_id is not None and _node_type(nodes_by_id.get(f"{prefix}{target_node}") or {}) != "input":
            print(
                f"[wf_runner] 忽略非法输入映射：目标 {target_node} 不是输入节点"
                f"（输入桥接只能指向子工作流的 input 节点）",
                flush=True,
            )
            continue
        value = outer_inputs.get(exposed, "")
        if value in (None, "", [], {}):
            print(
                f"[wf_runner] 输入映射 {exposed} → {target_node}.{target_port} 无值"
                f"（上游未连线或上游输出为空），本次跳过",
                flush=True,
            )
            continue
        injections.setdefault(f"{prefix}{target_node}", {})[target_port] = value
    return injections


# --------------------------------------------------------------------------- #
# 产物处理
# --------------------------------------------------------------------------- #
def _looks_like_path(value: str) -> bool:
    text = (value or "").strip()
    if not text or len(text) > 512 or "\n" in text:
        return False
    if text.startswith(("http://", "https://", "{", "[")):
        return False
    return os.path.splitext(text)[1] != ""


def _iter_paths(value, depth: int = 0):
    """递归产出 value 中所有看起来像文件路径的字符串。"""
    if depth > 4 or value in (None, "", [], {}):
        return
    if isinstance(value, str):
        if _looks_like_path(value):
            yield value
        return
    if isinstance(value, dict):
        for entry in value.values():
            yield from _iter_paths(entry, depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for entry in value:
            yield from _iter_paths(entry, depth + 1)


def _promote_outputs(outputs: dict, child_ws: Path, parent_ws: Path, runner_node_id: str) -> dict:
    """把终点产物从子工作区提升到父工作区 cache/，并改写为父工作区相对路径。

    子图节点以 child_ws 为 task_dir，其 outputs 中的路径是相对 child_ws 的
    （如 ``cache/x.mp4``）。若不提升，下游节点按 ``find_artifact`` 在父 cache
    中查找会落空，链路断开。提升后文件名带 ``_<runner_node_id>`` 后缀，
    符合项目产物命名约定。
    """
    parent_cache = parent_ws / "cache"
    parent_cache.mkdir(parents=True, exist_ok=True)
    cache: dict[str, str] = {}

    def _promote_one(value: str) -> str:
        if not _looks_like_path(value):
            return value
        if value in cache:
            return cache[value]
        src = Path(value)
        if not src.is_absolute():
            src = child_ws / value
        if not src.is_file():
            return value
        suffix = src.suffix
        dst_name = f"{src.stem}_{runner_node_id}{suffix}"
        dst = parent_cache / dst_name
        try:
            shutil.copy2(src, dst)
            promoted = f"cache/{dst_name}"
            cache[value] = promoted
            return promoted
        except OSError as exc:
            print(f"[wf_runner] 产物提升失败 {src} -> {dst}: {exc}", flush=True)
            return value

    def _walk(value, depth: int = 0):
        if depth > 4:
            return value
        if isinstance(value, str):
            return _promote_one(value)
        if isinstance(value, dict):
            return {k: _walk(v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v, depth + 1) for v in value]
        return value

    return _walk(outputs)


# --------------------------------------------------------------------------- #
# 输出收集
# --------------------------------------------------------------------------- #
def _pick_end_outputs(strategy: str, explicit_node_id: str, prefix: str, layers: list, outputs_by_node: dict) -> dict:
    """按输出策略挑出「终点节点」的输出。

    * explicit_node：取配置指定的终结节点（最可靠）；
    * auto_last_layer：取拓扑最后一层中有输出的节点（多个则按层内顺序合并）；
    * merge_all：合并所有有输出的节点。
    """
    if strategy == "explicit_node":
        target = f"{prefix}{explicit_node_id}" if explicit_node_id else ""
        if not target:
            raise ValueError("输出策略为「指定节点」但未配置终结节点")
        return dict(outputs_by_node.get(target) or {})

    if strategy == "merge_all":
        merged: dict[str, Any] = {}
        for node_id in outputs_by_node:
            merged.update(outputs_by_node.get(node_id) or {})
        return merged

    # auto_last_layer
    merged = {}
    last_layer = layers[-1] if layers else list(outputs_by_node.keys())
    for node_id in last_layer:
        outs = outputs_by_node.get(node_id) or {}
        if outs:
            merged.update(outs)
    if not merged:
        # 最后一层无输出（如全是预览节点）时退化为合并全部，避免拿到空结果
        for node_id in outputs_by_node:
            merged.update(outputs_by_node.get(node_id) or {})
    return merged


def _apply_output_mappings(mappings: list, prefix: str, outputs_by_node: dict) -> dict:
    """按显式输出映射取值：{暴露端口: 内部节点端口值}。"""
    outputs: dict[str, Any] = {}
    for mapping in mappings or []:
        if not isinstance(mapping, dict) or mapping.get("enabled") is False:
            continue
        exposed = str(mapping.get("exposedPortId") or "")
        internal_node = str(mapping.get("internalNodeId") or "")
        internal_port = str(mapping.get("internalPortId") or "")
        if not exposed or not internal_node or not internal_port:
            continue
        value = (outputs_by_node.get(f"{prefix}{internal_node}") or {}).get(internal_port, "")
        if value not in (None, "", [], {}):
            outputs[exposed] = value
    return outputs


# --------------------------------------------------------------------------- #
# 进度
# --------------------------------------------------------------------------- #
def _emit_progress(task_id: str, runner_node_id: str, workspace: Path, done: int, total: int, message: str) -> None:
    percent = int(min(100, max(0, done / max(total, 1) * 100)))
    try:
        with session_scope() as session:
            _event(session, task_id, "node_progress", {
                "node": runner_node_id, "node_id": runner_node_id, "step_id": runner_node_id,
                "progress": percent, "message": message, "status": "running",
            })
            node = session.scalar(select(TaskNode).where(TaskNode.task_id == task_id, TaskNode.node_key == runner_node_id))
            if node is not None:
                node.payload = {**node.payload, "progress": percent, "message": message}
            task = session.get(Task, task_id)
            if task is not None:
                _write_legacy_task(task, workspace)
    except Exception as exc:  # noqa: BLE001 - 进度上报失败不阻断执行
        print(f"[wf_runner] 进度上报失败: {exc}", flush=True)


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def run_workflow_runner_node(task_id: str, runner_node_id: str, workspace: Path, node_payload: dict) -> dict:
    """执行「工作流执行器」节点，返回与 step.run 一致的 {outputs, artifacts}。

    异常语义：子工作流内部任一节点失败即向上抛出，由 ``execute_workflow``
    把本节点标记为 failed；虚拟节点行保留，便于定位失败点。
    """
    started = time.monotonic()
    data = (node_payload or {}).get("data") or {}
    config = data.get("config") or {}
    ref = data.get("workflowRef") or {}

    wf_id = str(ref.get("wfId") or config.get("targetWorkflowId") or "").strip()
    if not wf_id:
        raise ValueError("未选择要执行的工作流，请在节点配置中选择目标工作流")

    # --- 递归保护：深度 + 环 ---
    stack = [str(x) for x in (config.get(_STACK_KEY) or []) if x]
    if wf_id in stack:
        raise ValueError(f"检测到工作流递归调用：{' -> '.join(stack + [wf_id])}")
    if len(stack) >= WF_RUNNER_MAX_DEPTH:
        raise ValueError(
            f"工作流嵌套层级超过上限（{WF_RUNNER_MAX_DEPTH}）：{' -> '.join(stack + [wf_id])}"
        )
    child_stack = stack + [wf_id]

    inner_nodes, inner_edges = _resolve_subgraph(ref, config)
    if not inner_nodes:
        raise ValueError(f"工作流 {wf_id} 中没有可执行的节点")

    # 输入节点设置项覆盖：合并进子工作流 input 节点的 config，
    # 使语言/变量等设置项、以及未被端口映射覆盖的默认输入都能生效
    inner_nodes = _apply_input_config_overrides(inner_nodes, config.get("inputConfigs") or {})

    # --- 执行目录 ---
    workspace_mode = str(config.get("workspaceMode") or "subdir")
    if workspace_mode == "inherit":
        child_ws = Path(workspace)
    else:
        child_ws = Path(workspace) / f"subwf_{runner_node_id}"
        # 重跑语义：虚拟节点每次重建，子目录同样重建，避免旧产物被误引用并控制磁盘占用
        if child_ws.exists():
            shutil.rmtree(child_ws, ignore_errors=True)
    (child_ws / "cache").mkdir(parents=True, exist_ok=True)
    (child_ws / "output").mkdir(parents=True, exist_ok=True)

    prefix = _prefix_for(runner_node_id)
    # 幂等：清掉上次执行残留的虚拟节点（执行失败时虚拟节点会保留以便排查）
    _delete_virtual_nodes(task_id, prefix)
    print(
        f"[wf_runner] 开始执行子工作流: runner={runner_node_id} wf={wf_id} "
        f"nodes={len(inner_nodes)} dir={child_ws}",
        flush=True,
    )

    # --- 创建虚拟节点 ---
    with session_scope() as session:
        vnode_ids, nodes_by_id = _create_virtual_nodes(
            session, task_id, inner_nodes, prefix, child_stack
        )
    if not vnode_ids:
        raise ValueError("子工作流没有可执行的节点")

    vedges: list[dict] = []
    for edge in inner_edges:
        if not isinstance(edge, dict):
            continue
        item_edge = dict(edge)
        item_edge["source"] = f"{prefix}{edge.get('source', '')}"
        item_edge["target"] = f"{prefix}{edge.get('target', '')}"
        item_edge["selected"] = False
        vedges.append(item_edge)

    # --- 输入 ---
    outer_inputs = _resolve_step_inputs(task_id, runner_node_id, workspace)
    injections = _build_injections(config.get("inputMappings") or [], outer_inputs, prefix, nodes_by_id)
    # 子工作流 input 节点 config：_resolve_inputs_from 据此向下游注入 source_language/target_language/var1/var2
    inner_input_config = _inner_input_config(inner_nodes)

    # 子流程内依赖 workspace/task.json 的步骤（如「路径转标题」读 input.videoPath）需要看到子图的输入：
    # 以 input 节点 config 为基础，再把本次实际注入的端口值回填成对应 config key（video → videoPath …）
    legacy_input = dict(inner_input_config)
    for vnode_id, port_values in (injections or {}).items():
        if _node_type(nodes_by_id.get(vnode_id) or {}) != "input":
            continue
        for port, value in (port_values or {}).items():
            config_key = _PORT_TO_INPUT_CONFIG_KEY.get(str(port))
            if config_key and value not in (None, "", [], {}):
                legacy_input[config_key] = value

    outputs_by_node: dict[str, dict] = {}
    layers = _build_layers(vnode_ids, vedges) or [[node_id] for node_id in vnode_ids]
    total = len(vnode_ids)

    def run_one(node_id: str) -> None:
        # 层内并行的工作线程不继承主线程上下文，需各自设置 legacy input 替身
        token = set_legacy_input_override(legacy_input)
        try:
            if _node_type(nodes_by_id.get(node_id) or {}) == "input":
                # 子工作流的 input 节点：直接产出，不交给 _run_node（否则会读父任务 input）
                outs = _input_fallback_outputs(nodes_by_id[node_id])
                outs.update(injections.get(node_id) or {})
                _mark_input_node_done(task_id, node_id, outs, child_ws)
                return
            step_inputs = _resolve_inputs_from(nodes_by_id, vedges, outputs_by_node, inner_input_config, node_id)
            step_inputs.update(injections.get(node_id) or {})
            _run_node(task_id, node_id, child_ws, step_factory=new_step_instance, step_inputs=step_inputs)
        finally:
            reset_legacy_input_override(token)

    main_token = set_legacy_input_override(legacy_input)
    try:
        done = 0
        for layer in layers:
            reason = _cancel_requested(task_id)
            if reason:
                raise TaskCancelledError(reason)
            if len(layer) == 1:
                run_one(layer[0])
            else:
                with ThreadPoolExecutor(max_workers=min(len(layer), WF_RUNNER_MAX_CONCURRENCY)) as pool:
                    futures = {pool.submit(run_one, node_id): node_id for node_id in layer}
                    first_exc = None
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception:  # noqa: BLE001 - 保留首个异常，整层结束后统一抛出
                            if first_exc is None:
                                first_exc = future.exception()
                    if first_exc is not None:
                        raise first_exc
            for node_id in layer:
                outputs_by_node[node_id] = _node_outputs(task_id, node_id)
            done += len(layer)
            _emit_progress(task_id, runner_node_id, workspace, done, total, f"子工作流 {done}/{total} 个节点完成")
    except Exception:
        # 失败时保留虚拟节点，便于在任务详情中定位子工作流内部的失败节点
        print(f"[wf_runner] 子工作流执行失败，保留虚拟节点以便排查: runner={runner_node_id}", flush=True)
        raise
    finally:
        reset_legacy_input_override(main_token)

    # --- 输出 ---
    mapped = _apply_output_mappings(config.get("outputMappings") or [], prefix, outputs_by_node)
    if mapped:
        end_outputs = mapped
    else:
        end_outputs = _pick_end_outputs(
            str(config.get("outputStrategy") or "auto_last_layer"),
            str(config.get("explicitEndNodeId") or ""),
            prefix, layers, outputs_by_node,
        )
        # 自动模式：按序填充固定输出端口 out_1..out_N，完整结果放 result
        filled: dict[str, Any] = {}
        for index, (key, value) in enumerate(end_outputs.items(), start=1):
            if index <= _OUTPUT_PORT_COUNT:
                filled[f"out_{index}"] = value
        if len(end_outputs) > _OUTPUT_PORT_COUNT:
            print(
                f"[wf_runner] 终点输出 {len(end_outputs)} 项，超出 {_OUTPUT_PORT_COUNT} 个固定端口，"
                f"超出部分仅写入 result",
                flush=True,
            )
        filled["result"] = end_outputs
        end_outputs = filled

    # --- 产物提升 ---
    if config.get("promoteOutputs", True) and child_ws != Path(workspace):
        end_outputs = _promote_outputs(end_outputs, child_ws, Path(workspace), runner_node_id)

    artifacts: list[str] = []
    seen: set[str] = set()
    for value in end_outputs.values():
        for path in _iter_paths(value):
            if path not in seen:
                seen.add(path)
                artifacts.append(path)

    # --- 收尾 ---
    _delete_virtual_nodes(task_id, prefix)
    if config.get("cleanupAfter", False) and child_ws != Path(workspace):
        try:
            shutil.rmtree(child_ws, ignore_errors=True)
        except OSError as exc:
            print(f"[wf_runner] 清理子工作区失败: {exc}", flush=True)

    print(
        f"[wf_runner] 子工作流执行完成: runner={runner_node_id} "
        f"outputs={len(end_outputs)} artifacts={len(artifacts)} 用时 {time.monotonic() - started:.1f}s",
        flush=True,
    )
    return {"outputs": end_outputs, "artifacts": artifacts}
