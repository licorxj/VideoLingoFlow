"""循环（Foreach）容器节点的运行时执行器。

设计要点
--------
循环节点（``data.kind == "loop"``）在画布上是一个容器，内部子图存放在
``data.loopMeta.internalWorkflow``。与组合节点（group）不同，**循环节点不在
normalize_workflow 阶段展开**：迭代次数取决于运行时才能拿到的 items 长度。
它作为普通节点参与主 DAG 分层（保证上游先跑完），进入 ``_run_node`` 后由本模块
在运行时展开子图并逐条执行。

关键约定
--------
* 迭代虚拟节点 key：``{loop_id}#{index:04d}__{内部节点 id}``
  - 含 ``_`` 前缀，因此产物文件名形如 ``xxx_{loop_id}#0003__inner.ext``，
    能被 ``_clear_nodes_artifacts`` 的"带 _<node_id> 后缀"兜底规则清理；
  - 含 ``#`` 便于前端过滤（画布上没有对应的真实节点）。
* 虚拟节点行是**临时态**：每次迭代前创建、迭代结束（成功或失败）后删除，
  保证 ``task.nodes`` 规模受控（task.json 每 5% 进度落盘一次，不能被撑爆）。
* 唯一的持久化记录是 manifest：``cache/loop_manifest_{loop_id}.json``，
  同时充当断点续跑的状态文件。产物本体不做物理归档，仅由 manifest 索引。

并发模型
--------
迭代级有界池（``iterationConcurrency``）+ 迭代内层内无界池（沿用主流程行为）。
资源令牌只在节点真正开跑时获取，持有者必定正在某个 worker 上运行并会释放，
因此不存在"等待者占满 worker 而持有者还在排队"的死锁。
"""
from __future__ import annotations

import copy
import glob as glob_module
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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
)
from backend.steps.step_registry import new_step_instance


# 迭代总数安全上限（防止上游误传超长列表把任务拖死）
LOOP_MAX_ITEMS = int(os.getenv("LOOP_MAX_ITEMS", "500"))
LOOP_MAX_CONCURRENCY = int(os.getenv("LOOP_MAX_CONCURRENCY", "16"))
_ITER_INDEX_WIDTH = 4

# 模板变量：{index} / {index:03d} / {total} / {item} / {item.field}
_TEMPLATE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)(?::([^}]*))?\}")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def iteration_prefix(loop_id: str, index: int) -> str:
    return f"{loop_id}#{index:0{_ITER_INDEX_WIDTH}d}__"


def manifest_relpath(loop_id: str) -> str:
    """manifest 相对任务工作区的路径（前端用 /api/files/stream 读取）。"""
    return f"cache/loop_manifest_{loop_id}.json"


def _manifest_path(workspace: Path, loop_id: str) -> Path:
    return workspace / "cache" / f"loop_manifest_{loop_id}.json"


def read_manifest(workspace: Path, loop_id: str) -> dict:
    path = _manifest_path(workspace, loop_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(workspace: Path, loop_id: str, manifest: dict) -> None:
    """原子写入 manifest（每完成一项增量落盘，异常中断也不丢进度）。"""
    path = _manifest_path(workspace, loop_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def _jsonable(value):
    """把任意迭代条目压成可 JSON 序列化的结构（用于 manifest 与比对）。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _same_item(left, right) -> bool:
    return json.dumps(_jsonable(left), ensure_ascii=False, sort_keys=True) == json.dumps(
        _jsonable(right), ensure_ascii=False, sort_keys=True
    )


# --------------------------------------------------------------------------- #
# 迭代对象解析
# --------------------------------------------------------------------------- #
def _coerce_items(raw, workspace: Path, depth: int = 0) -> list:
    """把上游/配置里形态各异的迭代对象收敛成 list。"""
    if depth > 3 or raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, tuple):
        return list(raw)
    if isinstance(raw, dict):
        # output_merge_list 输出 {"items":[{id,value,type}]} 之类的常见包装
        for key in ("items", "list", "files", "data", "results", "paths"):
            value = raw.get(key)
            if isinstance(value, (list, tuple)):
                return list(value)
        return [raw]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        # 1) 指向 JSON/TXT 文件的路径（相对任务工作区或绝对路径）
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = workspace / text
        if candidate.is_file() and candidate.suffix.lower() in (".json", ".txt"):
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = None
            if loaded is not None:
                return _coerce_items(loaded, workspace, depth + 1)
        # 2) 内联 JSON
        if text[0] in "[{":
            try:
                return _coerce_items(json.loads(text), workspace, depth + 1)
            except json.JSONDecodeError:
                pass
        # 3) 换行 / 分隔符切分
        if "\n" in text or "\r" in text:
            return [part.strip() for part in text.splitlines() if part.strip()]
        for sep in ("|", ";"):
            if sep in text:
                return [part.strip() for part in text.split(sep) if part.strip()]
        if "," in text:
            return [part.strip() for part in text.split(",") if part.strip()]
        return [text]
    return [raw]


def normalize_items(raw, *, workspace: Path, limit: int = LOOP_MAX_ITEMS) -> list:
    """归一化迭代对象：展平一层嵌套、去空值、按上限截断。"""
    items: list = []
    for entry in _coerce_items(raw, workspace):
        if isinstance(entry, list):
            items.extend(entry)
        else:
            items.append(entry)
    items = [item for item in items if item not in (None, "", [], {})]
    if limit and limit > 0 and len(items) > limit:
        items = items[:limit]
    return items


def resolve_items(config: dict, loop_inputs: dict, workspace: Path, items_port_id: str | None = None) -> list:
    """按 itemsSource 解析迭代对象，并应用 maxIterations 上限。

    ``items_port_id``：上游连线模式下承载迭代列表的端口（即 loopMeta.iterator
    的 exposedPortId）。循环节点的输入端口是映射端口而非固定的 ``items``，
    必须按实际连线端口取数，否则上游列表永远解析不到。
    """
    source = str(config.get("itemsSource") or "upstream")
    if source == "inline_json":
        raw = config.get("inlineItems") or ""
    elif source == "directory_glob":
        pattern = str(config.get("globPattern") or "").strip()
        if not pattern:
            return []
        candidate = Path(pattern)
        search_root = candidate if candidate.is_absolute() else (workspace / pattern)
        raw = sorted(
            path for path in glob_module.glob(str(search_root), recursive=True) if os.path.isfile(path)
        )
    else:
        raw = loop_inputs.get(items_port_id, "") if items_port_id else loop_inputs.get("items", "")
        if raw in (None, "", [], {}):
            # 兜底：未连到指定端口时取第一个非空输入
            for value in loop_inputs.values():
                if value not in (None, "", [], {}):
                    raw = value
                    break
    try:
        max_iterations = int(config.get("maxIterations") or 0)
    except (TypeError, ValueError):
        max_iterations = 0
    limit = max_iterations if max_iterations > 0 else LOOP_MAX_ITEMS
    return normalize_items(raw, workspace=workspace, limit=limit)


# --------------------------------------------------------------------------- #
# 模板变量渲染
# --------------------------------------------------------------------------- #
def _lookup(ctx: dict, key: str):
    if key in ctx:
        return ctx[key]
    if "." in key:
        head, _, tail = key.partition(".")
        base = ctx.get(head)
        if isinstance(base, dict):
            return base.get(tail, "")
        if isinstance(base, (list, tuple)) and tail.isdigit():
            position = int(tail)
            return base[position] if position < len(base) else ""
    return None


def render_value(value, ctx: dict):
    """递归渲染模板变量；未知变量原样保留，避免误伤正常文本。"""
    if isinstance(value, str):
        def _sub(match):
            found = _lookup(ctx, match.group(1))
            if found is None:
                return match.group(0)
            spec = match.group(2) or ""
            try:
                return format(found, spec) if spec else str(found)
            except (ValueError, TypeError):
                return str(found)
        return _TEMPLATE_PATTERN.sub(_sub, value)
    if isinstance(value, list):
        return [render_value(item, ctx) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, ctx) for key, item in value.items()}
    return value


def _iteration_context(config: dict, item, index: int, total: int) -> dict:
    item_alias = str(config.get("itemAlias") or "item")
    index_alias = str(config.get("indexAlias") or "index")
    return {
        "item": item,
        "index": index,
        "total": total,
        item_alias: item,
        index_alias: index,
    }


# --------------------------------------------------------------------------- #
# 迭代虚拟节点
# --------------------------------------------------------------------------- #
def _create_iteration_nodes(session, task_id: str, loop_id: str, meta: dict, index: int, item, total: int, config: dict):
    """为单次迭代创建虚拟 TaskNode 行，返回（节点 id 列表，重写后的边，节点快照表）。"""
    prefix = iteration_prefix(loop_id, index)
    internal = meta.get("internalWorkflow") or {}
    inner_nodes = internal.get("nodes") or []
    inner_edges = internal.get("edges") or []
    ctx = _iteration_context(config, item, index, total)

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
            # 变量替换只作用于 config，避免污染 id / 端口定义
            data["config"] = render_value(data.get("config") or {}, ctx)
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

    edges: list[dict] = []
    for edge in inner_edges:
        if not isinstance(edge, dict):
            continue
        item_edge = dict(edge)
        item_edge["source"] = f"{prefix}{edge.get('source', '')}"
        item_edge["target"] = f"{prefix}{edge.get('target', '')}"
        item_edge["selected"] = False
        edges.append(item_edge)

    session.flush()
    return node_ids, edges, nodes_by_id


def _delete_iteration_nodes(task_id: str, prefix: str) -> None:
    """删除某次迭代的临时虚拟节点行，保持 task.nodes 规模受控。"""
    with session_scope() as session:
        rows = [
            row for row in session.scalars(select(TaskNode).where(TaskNode.task_id == task_id)).all()
            if row.node_key.startswith(prefix)
        ]
        for row in rows:
            session.delete(row)
        session.flush()


def _node_outputs(task_id: str, node_id: str) -> dict:
    with session_scope() as session:
        row = session.scalar(select(TaskNode).where(TaskNode.task_id == task_id, TaskNode.node_key == node_id))
        if row is None:
            return {}
        result = (row.payload or {}).get("result")
        outputs = result.get("outputs") if isinstance(result, dict) else None
        return outputs if isinstance(outputs, dict) else {}


def _task_input_config(task_id: str) -> dict:
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            return {}
        return (task.payload or {}).get("input") or {}


def _iteration_injections(meta: dict, prefix: str, item, loop_inputs: dict) -> dict:
    """构造本次迭代需要注入的输入覆盖：{虚拟节点 id: {端口: 值}}。

    * 迭代来源端口（``loopMeta.iterator``）注入**当前条目**，每次迭代不同；
    * 其余输入映射端口注入上游原值，每次迭代相同（如固定的字幕、参考音频）。
    """
    iterator = meta.get("iterator") or {}
    iterator_port = str(iterator.get("exposedPortId") or "")
    target_node = str(iterator.get("targetNodeId") or "")
    target_port = str(iterator.get("targetPortId") or "")
    if not target_node or not target_port:
        # 兼容未写入 iterator 的手写数据：回退到第一个输入映射
        mappings = meta.get("inputMappings") or []
        if mappings and isinstance(mappings[0], dict):
            iterator_port = str(mappings[0].get("exposedPortId") or "")
            target_node = str(mappings[0].get("targetNodeId") or "")
            target_port = str(mappings[0].get("targetPortId") or "")

    injections: dict[str, dict] = {}
    for mapping in meta.get("inputMappings") or []:
        if not isinstance(mapping, dict):
            continue
        exposed = str(mapping.get("exposedPortId") or "")
        if not exposed or exposed == iterator_port:
            continue
        value = loop_inputs.get(exposed, "")
        if value in (None, "", [], {}):
            continue
        injections.setdefault(f"{prefix}{mapping.get('targetNodeId')}", {})[str(mapping.get("targetPortId"))] = value

    if target_node and target_port:
        injections.setdefault(f"{prefix}{target_node}", {})[target_port] = item
    return injections


# --------------------------------------------------------------------------- #
# 产物收集
# --------------------------------------------------------------------------- #
def _looks_like_path(value: str) -> bool:
    text = (value or "").strip()
    if not text or len(text) > 512 or "\n" in text:
        return False
    if text.startswith(("http://", "https://", "{", "[")):
        return False
    return os.path.splitext(text)[1] != ""


def _extract_paths(value, depth: int = 0) -> list:
    if depth > 4 or value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        return [value] if _looks_like_path(value) else []
    if isinstance(value, dict):
        found: list[str] = []
        for entry in value.values():
            found.extend(_extract_paths(entry, depth + 1))
        return found
    if isinstance(value, (list, tuple)):
        found = []
        for entry in value:
            found.extend(_extract_paths(entry, depth + 1))
        return found
    return []


def _collect_outputs(prefix: str, node_ids: list, outputs_by_node: dict) -> dict:
    """按**内部节点 id** 聚合本次迭代的输出，便于按 outputMappings 取值。"""
    collected: dict[str, dict] = {}
    for node_id in node_ids:
        outputs = outputs_by_node.get(node_id) or {}
        if not outputs:
            continue
        inner_id = node_id[len(prefix):] if node_id.startswith(prefix) else node_id
        collected[inner_id] = outputs
    return collected


def _collect_artifacts(node_ids: list, outputs_by_node: dict) -> list:
    artifacts: list[str] = []
    seen: set[str] = set()
    for node_id in node_ids:
        for value in (outputs_by_node.get(node_id) or {}).values():
            for path in _extract_paths(value):
                if path not in seen:
                    seen.add(path)
                    artifacts.append(path)
    return artifacts


# --------------------------------------------------------------------------- #
# 单次迭代
# --------------------------------------------------------------------------- #
def _run_iteration(
    task_id: str,
    loop_id: str,
    workspace: Path,
    meta: dict,
    config: dict,
    loop_inputs: dict,
    index: int,
    item,
    total: int,
    abort: threading.Event,
) -> dict:
    prefix = iteration_prefix(loop_id, index)
    started = time.monotonic()
    node_ids: list[str] = []
    try:
        with session_scope() as session:
            node_ids, edges, nodes_by_id = _create_iteration_nodes(
                session, task_id, loop_id, meta, index, item, total, config
            )
        if not node_ids:
            raise ValueError("循环体没有可执行节点")

        injections = _iteration_injections(meta, prefix, item, loop_inputs)
        input_config = _task_input_config(task_id)
        outputs_by_node: dict[str, dict] = {}
        layers = _build_layers(node_ids, edges) or [[node_id] for node_id in node_ids]

        def run_one(node_id: str) -> None:
            step_inputs = _resolve_inputs_from(nodes_by_id, edges, outputs_by_node, input_config, node_id)
            step_inputs.update(injections.get(node_id) or {})
            # 迭代并发：每个迭代持独立 step 实例，避免注册表单例状态互相覆盖
            _run_node(task_id, node_id, workspace, step_factory=new_step_instance, step_inputs=step_inputs)

        for layer in layers:
            if abort.is_set():
                raise TaskCancelledError("loop_aborted")
            reason = _cancel_requested(task_id)
            if reason:
                raise TaskCancelledError(reason)
            if len(layer) == 1:
                run_one(layer[0])
            else:
                # 迭代内层内沿用主流程的无界池（层内节点少，且令牌持有者必定在跑，无死锁）
                with ThreadPoolExecutor(max_workers=len(layer)) as pool:
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

        return {
            "index": index,
            "item": _jsonable(item),
            "status": "succeeded",
            "outputs": _collect_outputs(prefix, node_ids, outputs_by_node),
            "artifacts": _collect_artifacts(node_ids, outputs_by_node),
            "error": "",
            "elapsed": round(time.monotonic() - started, 2),
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except TaskCancelledError as exc:
        return {
            "index": index,
            "item": _jsonable(item),
            "status": "cancelled",
            "outputs": {},
            "artifacts": [],
            "error": str(exc) or "cancelled",
            "elapsed": round(time.monotonic() - started, 2),
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:  # noqa: BLE001 - 单项失败要落进 manifest，由上层按策略决定走向
        return {
            "index": index,
            "item": _jsonable(item),
            "status": "failed",
            "outputs": {},
            "artifacts": [],
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed": round(time.monotonic() - started, 2),
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    finally:
        _delete_iteration_nodes(task_id, prefix)


# --------------------------------------------------------------------------- #
# 进度与收尾
# --------------------------------------------------------------------------- #
_STATUS_LABEL = {"succeeded": "完成", "failed": "失败", "cancelled": "取消"}


def _emit_progress(task_id: str, loop_id: str, workspace: Path, done: int, total: int, index: int, record: dict) -> None:
    percent = int(min(100, max(0, done / max(total, 1) * 100)))
    status = str(record.get("status") or "succeeded")
    message = f"[{done}/{total}] 第 {index} 项{_STATUS_LABEL.get(status, status)}"
    if record.get("error"):
        message = f"{message}：{record['error']}"
    with session_scope() as session:
        _event(session, task_id, "node_progress", {
            "node": loop_id, "node_id": loop_id, "step_id": loop_id,
            "progress": percent, "message": message, "status": "running",
            "loop_index": index, "loop_total": total, "loop_done": done, "loop_item_status": status,
        })
        node = session.scalar(select(TaskNode).where(TaskNode.task_id == task_id, TaskNode.node_key == loop_id))
        if node is not None:
            node.payload = {
                **node.payload,
                "progress": percent,
                "message": message,
                "loop": {"index": index, "total": total, "done": done, "status": status},
            }
        task = session.get(Task, task_id)
        if task is not None:
            _write_legacy_task(task, workspace)


def _loop_outputs(loop_id: str, meta: dict, manifest: dict) -> dict:
    outputs = {
        "count": int(manifest.get("total") or 0),
        "results": manifest_relpath(loop_id),
    }
    # 输出映射端口：按迭代顺序聚合成列表，下游（如产物归档）可直接消费
    for mapping in meta.get("outputMappings") or []:
        if not isinstance(mapping, dict) or mapping.get("enabled") is False:
            continue
        exposed = str(mapping.get("exposedPortId") or "")
        internal_node = str(mapping.get("internalNodeId") or "")
        internal_port = str(mapping.get("internalPortId") or "")
        if not exposed or not internal_node or not internal_port:
            continue
        values = []
        for record in manifest.get("items") or []:
            if not isinstance(record, dict) or record.get("status") != "succeeded":
                continue
            value = ((record.get("outputs") or {}).get(internal_node) or {}).get(internal_port, "")
            if value not in (None, "", [], {}):
                values.append(value)
        if values:
            outputs[exposed] = values
    return outputs


def _loop_artifacts(manifest: dict) -> list:
    artifacts: list[str] = []
    seen: set[str] = set()
    for record in manifest.get("items") or []:
        if not isinstance(record, dict):
            continue
        for path in record.get("artifacts") or []:
            if path not in seen:
                seen.add(path)
                artifacts.append(path)
    return artifacts


def _clamp_concurrency(config: dict) -> int:
    try:
        value = int(config.get("iterationConcurrency") or 1)
    except (TypeError, ValueError):
        value = 1
    return max(1, min(value, LOOP_MAX_CONCURRENCY))


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def run_loop_node(task_id: str, loop_node_id: str, workspace: Path, node_payload: dict) -> dict:
    """执行循环容器节点，返回与 step.run 一致的 {outputs, artifacts}。

    异常语义：``onItemError == "stop"`` 且有失败项时抛 RuntimeError，由
    ``execute_workflow`` 统一把循环节点标记为 failed；其余策略只记录不抛出。
    """
    data = (node_payload or {}).get("data") or {}
    meta = data.get("loopMeta") or {}
    config = data.get("config") or {}
    if not meta:
        raise ValueError("循环节点缺少 loopMeta 定义，请重新创建循环")

    loop_inputs = _resolve_step_inputs(task_id, loop_node_id, workspace)
    items_port = (meta.get("iterator") or {}).get("exposedPortId") or None
    items = resolve_items(config, loop_inputs, workspace, items_port)
    total = len(items)
    if total == 0:
        raise ValueError("未解析到任何迭代条目，请检查「迭代对象来源」配置与上游连线")

    concurrency = _clamp_concurrency(config)
    on_error = str(config.get("onItemError") or "stop")
    print(
        f"[loop_runtime] 开始循环: loop={loop_node_id} items={total} concurrency={concurrency} onItemError={on_error}",
        flush=True,
    )

    # 断点续跑：沿用上次 manifest 中「条目未变化且已成功」的记录
    previous = read_manifest(workspace, loop_node_id)
    previous_items: dict[int, dict] = {}
    for record in previous.get("items") or []:
        if not isinstance(record, dict):
            continue
        try:
            index = int(record.get("index"))
        except (TypeError, ValueError):
            continue
        previous_items[index] = record

    skipped: list[int] = []
    todo: list[int] = []
    for index, item in enumerate(items):
        prev = previous_items.get(index)
        if prev and prev.get("status") == "succeeded" and _same_item(prev.get("item"), item):
            skipped.append(index)
            continue
        todo.append(index)
    if skipped:
        print(f"[loop_runtime] 断点续跑：跳过 {len(skipped)} 个已完成条目", flush=True)

    manifest = {
        "loop_node_id": loop_node_id,
        "total": total,
        "concurrency": concurrency,
        "onItemError": on_error,
        "itemsSource": str(config.get("itemsSource") or "upstream"),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "items": [],
    }
    manifest["items"] = [
        previous_items[index] if index in previous_items and index in skipped else {
            "index": index,
            "item": _jsonable(items[index]),
            "status": "pending",
            "outputs": {},
            "artifacts": [],
            "error": "",
        }
        for index in range(total)
    ]
    write_manifest(workspace, loop_node_id, manifest)

    abort = threading.Event()
    done = len(skipped)
    if todo:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(
                    _run_iteration,
                    task_id, loop_node_id, workspace, meta, config, loop_inputs,
                    index, items[index], total, abort,
                ): index
                for index in todo
            }
            try:
                for future in as_completed(futures):
                    index = futures[future]
                    record = future.result()
                    manifest["items"][index] = record
                    done += 1
                    manifest["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    write_manifest(workspace, loop_node_id, manifest)
                    _emit_progress(task_id, loop_node_id, workspace, done, total, index, record)
                    if record.get("status") != "succeeded" and on_error == "stop":
                        # 停止策略：置中止标志，已提交的迭代会在下一个层边界退出
                        abort.set()
            finally:
                abort.set()

    succeeded = sum(1 for record in manifest["items"] if isinstance(record, dict) and record.get("status") == "succeeded")
    failures = [
        record for record in manifest["items"]
        if isinstance(record, dict) and record.get("status") != "succeeded"
    ]
    manifest["succeeded"] = succeeded
    manifest["failed"] = len(failures)
    manifest["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_manifest(workspace, loop_node_id, manifest)
    print(f"[loop_runtime] 循环结束: loop={loop_node_id} 成功 {succeeded}/{total}，失败 {len(failures)}", flush=True)

    if failures and on_error == "stop":
        first = failures[0]
        raise RuntimeError(f"循环第 {first.get('index')} 项失败：{first.get('error') or '未知错误'}")

    return {
        "outputs": _loop_outputs(loop_node_id, meta, manifest),
        "artifacts": _loop_artifacts(manifest),
    }
