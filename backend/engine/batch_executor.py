import json
import os
import threading
import time
import uuid
from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.config.config_manager import config
from backend.control_plane.database import session_scope
from backend.control_plane.models import Task, TaskNode
from backend.control_plane.workflow_runtime import DISPATCH_STALE, _node_type, _resource_for, _workspace, _write_legacy_task, queue_for, request_cancel, request_delete, submit_workflow, _clear_workspace_cache


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted", "archived"}
# 批次视图排除的状态：已删除与删除中断残留（历史遗留的 stuck deleting 记录）、
# 已归档任务（产物已挪到外部归档目录，记录保留在历史项目的已归档列表）。
# 不应再出现在批量页面，否则删除/归档后条目仍显示。
BATCH_HIDDEN_STATUSES = {"deleted", "deleting", "archived"}
WORKBENCH_TASK_STATUS = {
    "succeeded": "completed",
    "queued": "created",
    "stopping": "running",
    "deleted": "cancelled",
    "deleting": "cancelled",
}
# 投递宽限期：queued 且刚投递不久的任务视为"仍在队列排队"（避免重复投递/误判僵尸）。
# 超过该时长既没有节点开跑、也没有新投递，则视为僵尸排队，可被重新投递/放行同步。
DISPATCH_LIVE_GRACE_SECONDS = float(os.getenv("CONTROL_PLANE_DISPATCH_LIVE_GRACE_SECONDS", "120") or 120)
WORKBENCH_NODE_STATUS = {
    "succeeded": "completed",
    "queued": "pending",
}


def _workflow_path(workflow_id: str) -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "workflows", f"{workflow_id}.json",
    )


def _load_workflow(workflow_id: str) -> dict:
    path = _workflow_path(workflow_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Workflow {workflow_id} not found")
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _derive_task_name(input_config: dict) -> str:
    for key in ("videoPath", "audioPath", "subtitlePath"):
        value = input_config.get(key, "")
        if value:
            return os.path.splitext(os.path.basename(value))[0]
    url = input_config.get("url", "")
    if url:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.path.strip("/").split("/")[-1] or parsed.netloc[:30]
    return ""


def _trace(message: str) -> None:
    print(f"[TaskTrace][Batch] {message}", flush=True)


def _resource_for_snapshot(node_type: str, snapshot: dict) -> str:
    """按节点快照解析资源类（生图节点需按接口动态判定）。

    兼容不接受 node 参数的旧版控制平面二进制：降级为只按节点类型判定，避免 TypeError。
    """
    try:
        return _resource_for(node_type, snapshot)
    except TypeError:
        return _resource_for(node_type)


def _batch_meta(task: Task) -> dict:
    return (task.payload or {}).get("batch", {})


def _workbench_task_status(status: str) -> str:
    return WORKBENCH_TASK_STATUS.get(status, status)


def _task_ui_status(task: Task) -> str:
    payload = task.payload or {}
    if task.status == "paused" and payload.get("await_manual_resume"):
        return "interrupted"
    return _workbench_task_status(task.status)


def _workbench_node_status(status: str) -> str:
    return WORKBENCH_NODE_STATUS.get(status, status)


def _has_live_dispatch(task: Task) -> bool:
    """queued 任务是否真的有在途投递（仍可能被 worker 领走执行）。

    queued 只表示「曾经下发过 Celery 消息」，消息可能已丢失（broker 重启 / 消息被丢弃 /
    worker 未启动），任务会永久卡在 queued（批量页显示「待执行」）：既不该拦住同步工作流，
    也不该让「继续 / 重跑」点下去毫无反应。判定为「仍有在途投递」的依据：
      1. dispatch_token 不是哨兵 __stale__（哨兵 = 已复位，明确没有有效投递）；
      2. 且满足其一：任务内已有 queued/running 的节点（worker 已领走并在跑），
         或投递时间在宽限期内（消息大概率还在队列里排队，避免重复投递）。
    """
    if task.status != "queued":
        return False
    payload = task.payload or {}
    if payload.get("dispatch_token") == DISPATCH_STALE:
        return False
    if any(node.status in {"queued", "running"} for node in task.nodes):
        return True
    try:
        age = time.time() - float(payload.get("dispatch_token_at"))
    except (TypeError, ValueError):
        # 无投递时间戳（旧数据）：无法证明还有在途投递 → 按可重新投递处理
        return False
    return age <= DISPATCH_LIVE_GRACE_SECONDS


def _task_payload(task: Task) -> dict:
    payload = task.payload or {}
    meta = _batch_meta(task)
    return {
        "task_id": task.id,
        "task_name": meta.get("task_name", task.id),
        "status": _task_ui_status(task),
        "index": meta.get("index", 0),
        "input": payload.get("input", {}),
        "nodes": {
            node.node_key: {
                "nodeType": (node.payload or {}).get("data", {}).get("nodeType", ""),
                "label": (node.payload or {}).get("data", {}).get("label", ""),
                "status": _workbench_node_status(node.status),
                "progress": 100 if node.status == "succeeded" else int((node.payload or {}).get("progress", 0) or 0),
                # 运行中节点返回当前 message；若后续进度覆盖了等待提示，则回退到 wait_message，避免前端一闪而过
                "message": (node.payload or {}).get("message", "") or (node.payload or {}).get("wait_message", ""),
                "error": ((node.payload or {}).get("message") or node.error_class or "") if node.status == "failed" else (node.error_class or ""),
                "error_class": node.error_class or "",
            }
            for node in task.nodes
        },
        "started_at": task.created_at.isoformat() if task.created_at else "",
        "finished_at": task.updated_at.isoformat() if task.status in TERMINAL_STATUSES and task.updated_at else "",
        "error": task.error_class or "",
    }


def _batch_status(tasks: list[Task]) -> str:
    statuses = [_task_ui_status(task) for task in tasks]
    if not statuses:
        return "created"
    if all(status == "succeeded" for status in statuses):
        return "completed"
    if all(status in TERMINAL_STATUSES for status in statuses):
        return "partial" if "succeeded" in statuses else "failed"
    if any(status == "running" for status in statuses):
        return "running"
    if any(status == "interrupted" for status in statuses):
        return "interrupted"
    if any(status == "paused" for status in statuses):
        return "paused"
    if any(status in {"queued", "stopping"} for status in statuses):
        return "running"
    return "created"


class BatchExecutor:
    def __init__(self):
        # 每个 batch 的后台投递线程 + 停止信号（stop/pause/delete 时 set，投递循环据此中止）
        self._delivery_threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}

    def _get_max_workers(self) -> int:
        return int(config.get("batch.max_concurrent_tasks", 3))

    def set_max_workers(self, count: int):
        config.set("batch.max_concurrent_tasks", max(1, min(count, 20)))

    def set_task_start_interval(self, interval: float):
        config.set("batch.task_start_interval", max(0, interval))

    def _stop_event(self, batch_id: str) -> threading.Event:
        evt = self._stop_events.get(batch_id)
        if evt is None:
            evt = threading.Event()
            self._stop_events[batch_id] = evt
        return evt

    def _signal_stop(self, batch_id: str) -> None:
        evt = self._stop_events.get(batch_id)
        if evt is not None:
            evt.set()

    def _start_delivery(self, batch_id: str, mode: str) -> None:
        """启动后台投递线程（幂等：同 batch 已有活跃线程则不重复启动）。"""
        if batch_id in self._delivery_threads and self._delivery_threads[batch_id].is_alive():
            _trace(f"批次 {batch_id[:8]} 已有投递线程在运行，忽略重复启动（mode={mode}）")
            return
        # 新投递轮次：清掉旧停止信号，重新计数
        self._stop_events.pop(batch_id, None)
        thread = threading.Thread(target=self._deliver_loop, args=(batch_id, mode), daemon=True, name=f"batch-deliver-{batch_id[:8]}")
        self._delivery_threads[batch_id] = thread
        thread.start()
        _trace(f"启动批次投递线程 batch={batch_id[:8]} mode={mode} thread={thread.name}")

    def _deliver_loop(self, batch_id: str, mode: str) -> None:
        """后台投递循环：按 max_concurrent_tasks 限流 + task_start_interval 间隔，可被停止信号中止。"""
        evt = self._stop_event(batch_id)
        interval = max(0.0, float(config.get("batch.task_start_interval", 0)))
        parallel = max(1, self._get_max_workers())
        # 统计当前批次所有任务的投递顺序（按创建时间）
        with session_scope() as session:
            order = [task.id for task in session.scalars(select(Task).where(Task.legacy_key.like(f"batch:{batch_id}:%")).order_by(Task.created_at)).all()]
        _trace(
            f"开始批次投递 batch={batch_id[:8]} mode={mode} tasks={len(order)} "
            f"parallel={parallel}(实际并行由 Worker 并发控制) start_interval={interval:.1f}s"
        )
        try:
            for task_id in order:
                if evt.is_set():
                    _trace(f"批次 {batch_id[:8]} 收到停止信号，终止后续投递")
                    break
                # 投递 = 入队排队，不按「并行数」阻塞：整批一次投进队列，由 Worker 按并发数
                # 逐个取走执行，跑完一个自动续下一个。若这里按在途数阻塞，批量布置时后面的
                # 任务要等前面跑完才入队，用户会看到"只有前 N 个被接受、其余都失败"的错觉。
                with session_scope() as session:
                    task = session.get(Task, task_id)
                    if task is None or task.status in {"running", "succeeded", "deleted"}:
                        continue
                try:
                    # force：本轮是用户显式启动/继续，僵尸排队（queued 但消息已丢失）也要重新投递，
                    # 否则任务会永远卡在「待执行」；重复执行由 dispatch fencing 兜底。
                    self._enqueue(task_id, mode, force=True)
                except RuntimeError:
                    _trace(f"任务 {task_id[:8]} 投递失败，停止当前批次投递")
                    break  # Celery 不可用等，停止投递
                # 启动间隔（分段 sleep，期间响应停止信号）
                slept = 0.0
                while slept < interval and not evt.is_set():
                    step = min(0.2, interval - slept)
                    time.sleep(step)
                    slept += step
        finally:
            self._delivery_threads.pop(batch_id, None)
            _trace(f"批次投递线程结束 batch={batch_id[:8]} mode={mode}")

    def _tasks_for_batch(self, batch_id: str) -> list[Task]:
        with session_scope() as session:
            tasks = session.scalars(select(Task).options(selectinload(Task.nodes)).order_by(Task.created_at).where(
                Task.legacy_key.like(f"batch:{batch_id}:%"),
                Task.status.notin_(BATCH_HIDDEN_STATUSES),
            )).unique().all()
            if not tasks:
                raise FileNotFoundError(f"Batch {batch_id} not found")
            return tasks

    def _batch_detail(self, batch_id: str, tasks: list[Task]) -> dict:
        first = tasks[0]
        meta = _batch_meta(first)
        workflow = (first.payload or {}).get("workflow", {})
        return {
            "batch_id": batch_id,
            "batch_name": meta.get("batch_name", f"batch_{batch_id[:8]}"),
            "name": meta.get("batch_name", f"batch_{batch_id[:8]}"),
            "workflow_id": meta.get("workflow_id", workflow.get("id", "")),
            "workflow_name": meta.get("workflow_name", workflow.get("name", "")),
            "workflow": workflow,
            "status": _batch_status(tasks),
            "created_at": first.created_at.isoformat() if first.created_at else "",
            "tasks": [_task_payload(task) for task in tasks],
            "workflow_nodes": [
                {"id": node.get("id", ""), "nodeType": node.get("data", {}).get("nodeType", ""), "label": node.get("data", {}).get("label", "")}
                for node in workflow.get("nodes", [])
            ],
        }

    def create_batch(self, workflow_id: str, tasks_input: list, batch_name: str = "", common_config: Optional[dict] = None) -> dict:
        workflow = _load_workflow(workflow_id)
        batch_id = uuid.uuid4().hex[:12]
        name = batch_name or f"batch_{batch_id[:8]}"
        common = common_config or {}
        _trace(f"创建批次 batch={batch_id[:8]} workflow={workflow_id} name={name} tasks={len(tasks_input)}")
        for index, raw_input in enumerate(tasks_input):
            input_config = {**common, **raw_input}
            task_name = _derive_task_name(input_config) or f"task_{index + 1}"
            task_id = uuid.uuid4().hex
            task, _ = submit_workflow(workflow, input_config, mode="batch", task_id=task_id, enqueue=False, idempotency_scope=task_id)
            with session_scope() as session:
                stored = session.get(Task, task.id)
                stored.legacy_key = f"batch:{batch_id}:{stored.id}"
                stored.payload = {
                    **stored.payload,
                    "batch": {
                        "batch_id": batch_id,
                        "batch_name": name,
                        "workflow_id": workflow_id,
                        "workflow_name": workflow.get("name", workflow_id),
                        "task_name": task_name,
                        "index": index,
                    },
                }
            # 复制一份全局工作流快照到子任务根目录，供子任务画布编辑/重跑使用（与全局解耦）
            wdir = _workspace(task.id)
            wdir.mkdir(parents=True, exist_ok=True)
            (wdir / "workflow.json").write_text(
                json.dumps((task.payload or {}).get("workflow", workflow), ensure_ascii=False),
                encoding="utf-8",
            )
            _trace(f"批次 {batch_id[:8]} 注册任务 #{index + 1} task={task.id[:8]} name={task_name}")
        return {"batch_id": batch_id, "batch_name": name, "task_count": len(tasks_input), "status": "created"}

    def list_batches(self) -> list:
        with session_scope() as session:
            # 切勿在此 selectinload(Task.nodes)：批次列表只需任务级状态
            # （_batch_status 仅读 task.status / payload.await_manual_resume，不碰 nodes），
            # 而 TaskNode.payload 是「节点完整快照 + 运行结果」的大 JSON。跨页全量加载
            # 所有批次任务的全部节点会耗尽内存（曾表现为 MemoryError）。
            # 需要节点明细时，由 get_batch_detail 按批次（仅当前页）单独加载。
            tasks = session.scalars(select(Task).where(
                Task.legacy_key.like("batch:%"),
                Task.status.notin_(BATCH_HIDDEN_STATUSES),
            ).order_by(Task.created_at.desc())).all()
        grouped = defaultdict(list)
        for task in tasks:
            grouped[_batch_meta(task).get("batch_id", task.legacy_key.split(":", 1)[-1])].append(task)
        return [
            {
                "id": batch_id,
                "name": _batch_meta(items[0]).get("batch_name", f"batch_{batch_id[:8]}"),
                "workflow_id": _batch_meta(items[0]).get("workflow_id", ""),
                "workflow_name": _batch_meta(items[0]).get("workflow_name", ""),
                "status": _batch_status(items),
                "task_count": len(items),
                "task_ids": [task.id for task in items],
                "created_at": items[0].created_at.isoformat() if items[0].created_at else "",
            }
            for batch_id, items in grouped.items()
        ]

    def get_batch_page(self, page: int, page_size: int) -> dict:
        batches = self.list_batches()
        selected = batches[(page - 1) * page_size:page * page_size]
        return {"batches": [self.get_batch_detail(item["id"]) for item in selected], "total": len(batches), "page": page, "page_size": page_size}

    def get_batch_detail(self, batch_id: str) -> dict:
        return self._batch_detail(batch_id, self._tasks_for_batch(batch_id))

    def get_archive_files(self, batch_id: str) -> dict:
        """列出批次下各任务的归档产物清单（供归档弹窗展示）。"""
        from backend.engine.batch_archive import describe_batch_tasks

        tasks = self._tasks_for_batch(batch_id)
        detail = self._batch_detail(batch_id, tasks)
        return {
            "batch_id": batch_id,
            "batch_name": detail.get("name", ""),
            "tasks": describe_batch_tasks(tasks),
        }

    def archive_batch(self, batch_id: str, target_dir: str, selections: Optional[dict] = None) -> dict:
        """把批次下任务产物归档到目标文件夹，成功后在库中标记为已归档。"""
        from backend.engine.batch_archive import archive_batch_tasks

        _trace(f"归档批次 batch={batch_id[:8]} target={target_dir}")
        tasks = self._tasks_for_batch(batch_id)
        result = archive_batch_tasks(tasks, target_dir, selections)
        _trace(
            f"归档批次完成 batch={batch_id[:8]} archived={len(result.get('archived', []))} "
            f"blocked={len(result.get('blocked', []))} failed={len(result.get('failed', []))}"
        )
        return {"batch_id": batch_id, **result}

    def _enqueue(self, task_id: str, mode: str = "new", force: bool = False) -> bool:
        """投递单个任务，返回是否真正下发了执行消息。

        force=False 时，卡在 queued 且带有效 dispatch_token 的任务会被单飞保护静默拦下
        （返回 False，前端表现为点「继续」没反应）。用户显式触发的继续/重跑/启动一律
        传 force=True，让僵尸排队能重新投递（重复执行由 fencing token 兜底）。
        """
        with session_scope() as session:
            task = session.get(Task, task_id)
            if task is None:
                return False
            workflow = (task.payload or {}).get("workflow", {})
            input_config = (task.payload or {}).get("input", {})
            batch_meta = _batch_meta(task)
            task_name = batch_meta.get("task_name", task.id[:8])
            batch_id = batch_meta.get("batch_id", "")
        _trace(
            f"投递任务 task={task_id[:8]} name={task_name} batch={batch_id[:8] if batch_id else '-'} "
            f"mode={mode} workflow={workflow.get('id', '') or workflow.get('name', '')}"
        )
        try:
            _task, dispatched = submit_workflow(
                workflow, input_config, mode=mode, task_id=task_id, enqueue=True, idempotency_scope=task_id, force=force
            )
        except TypeError:
            # 控制平面走的是未重新编译的旧二进制（submit_workflow 无 force 参数）：降级调用，
            # 避免用户点「继续」直接 500。此时僵尸排队仍无法重投（行为与修复前一致）。
            _trace(f"控制平面不支持 force 投递，降级为普通投递 task={task_id[:8]}")
            _task, dispatched = submit_workflow(
                workflow, input_config, mode=mode, task_id=task_id, enqueue=True, idempotency_scope=task_id
            )
        if not dispatched:
            _trace(f"任务 {task_id[:8]} 未投递（状态为在途/不可重投），本次操作无实际效果")
        return dispatched

    def start_batch(self, batch_id: str) -> dict:
        tasks = self._tasks_for_batch(batch_id)
        _trace(f"启动批次 batch={batch_id[:8]} tasks={len(tasks)}")
        self._start_delivery(batch_id, "batch")
        return {"batch_id": batch_id, "status": "running", "task_count": len(tasks), "submitted": len(tasks)}

    def stop_batch(self, batch_id: str) -> dict:
        self._signal_stop(batch_id)
        _trace(f"停止批次 batch={batch_id[:8]}")
        for task in self._tasks_for_batch(batch_id):
            request_cancel(task.id, "batch_stopped")
        return {"batch_id": batch_id, "status": "stopped"}

    def sync_workflow(self, batch_id: str, workflow_id: str = "") -> dict:
        tasks = self._tasks_for_batch(batch_id)
        # 只有真的在执行（running/stopping）或仍可能被 worker 领走（queued + 有在途投递）
        # 才拦截同步。卡在 queued 的僵尸排队（消息已丢失、一直显示「待执行」）不应再拦住用户，
        # 否则既不能同步、又点不动「继续」，任务永远出不来。
        active_task_ids = [
            task.id for task in tasks
            if task.status in {"running", "stopping"} or _has_live_dispatch(task)
        ]
        if active_task_ids:
            raise RuntimeError(f"批次存在执行中的任务，无法同步工作流: {', '.join(active_task_ids)}")
        zombie_task_ids = {task.id for task in tasks if task.status == "queued" and not _has_live_dispatch(task)}
        if zombie_task_ids:
            _trace(f"批次 {batch_id[:8]} 存在 {len(zombie_task_ids)} 个僵尸排队任务，同步后重置为待投递")
        workflow_id = workflow_id or _batch_meta(tasks[0]).get("workflow_id", "")
        workflow = _load_workflow(workflow_id)
        with session_scope() as session:
            for task in session.scalars(select(Task).where(Task.legacy_key.like(f"batch:{batch_id}:%"))).all():
                nodes_by_id = {node.get("id", ""): node for node in workflow.get("nodes", [])}
                existing_nodes = {node.node_key: node for node in task.nodes}
                for node_id, node_snapshot in nodes_by_id.items():
                    if not node_id:
                        continue
                    node_type = _node_type(node_snapshot)
                    # 传节点快照：生图节点按所选接口动态判定（云端免令牌 / 本地 ComfyUI 走 gpu）
                    resource = _resource_for_snapshot(node_type, node_snapshot)
                    existing = existing_nodes.get(node_id)
                    if existing is None:
                        session.add(TaskNode(
                            task_id=task.id,
                            node_key=node_id,
                            status="pending",
                            resource_class=resource,
                            queue=queue_for(resource),
                            payload={**node_snapshot, "result": {}},
                        ))
                        continue
                    old_payload = existing.payload or {}
                    old_type = _node_type(old_payload)
                    existing.resource_class = resource
                    existing.queue = queue_for(resource)
                    if old_type == node_type:
                        runtime_fields = {
                            key: old_payload[key]
                            for key in ("result", "progress", "message")
                            if key in old_payload
                        }
                        existing.payload = {**node_snapshot, **runtime_fields}
                    else:
                        existing.status = "pending"
                        existing.worker_id = None
                        existing.cancel_reason = None
                        existing.error_class = None
                        existing.checkpoint_key = None
                        existing.payload = {**node_snapshot, "result": {}}
                task.payload = {**task.payload, "workflow": workflow, "batch": {**_batch_meta(task), "workflow_id": workflow_id, "workflow_name": workflow.get("name", workflow_id)}}
                if task.id in zombie_task_ids:
                    # 同步后把它标记成「当前没有任何有效投递」，后续点「继续」才不会又被单飞保护吞掉
                    task.payload = {**task.payload, "dispatch_token": DISPATCH_STALE}
                workspace = _workspace(task.id)
                workspace.mkdir(parents=True, exist_ok=True)
                (workspace / "workflow.json").write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
                session.flush()
                _write_legacy_task(task, workspace)
        return {"batch_id": batch_id, "workflow_id": workflow_id, "synced": True}

    def _queue_stats(self) -> dict:
        """批量任务的队列概览：队列排队中 / 正在执行的数量（用于投递结果提示）。"""
        with session_scope() as session:
            tasks = session.scalars(select(Task).where(
                Task.legacy_key.like("batch:%"),
                Task.status.in_(("queued", "running", "stopping")),
            )).all()
        return {
            "queued": sum(1 for task in tasks if task.status == "queued"),
            "running": sum(1 for task in tasks if task.status in {"running", "stopping"}),
        }

    def dispatch_tasks(self, batch_id: str, task_ids: list, mode: str = "resume") -> dict:
        """把选中任务批量投递到执行队列排队（投递 ≠ 立即执行）。

        - mode="resume"：断点继续，保留已成功节点，只跑未完成部分（「投递任务 / 选中继续」用）
        - mode="retry"：从头执行（清 cache、全量重建节点，「选中重跑」用）

        刻意不做「在途已达上限就拒绝」：排队交给队列承担，真正同时执行数由 Worker 并发
        （=batch.max_concurrent_tasks）决定。否则批量布置时除前 N 个外全部失败，
        完全达不到"一次投递整批、队列自动续跑"的目的。
        """
        tasks = {task.id: task for task in self._tasks_for_batch(batch_id)}
        dispatched: list = []
        skipped: list = []
        for task_id in task_ids:
            task = tasks.get(task_id)
            if task is None:
                skipped.append({"task_id": task_id, "reason": "不在当前批次"})
                continue
            if task.status in {"running", "stopping"}:
                skipped.append({"task_id": task_id, "reason": "正在执行"})
                continue
            if task.status == "succeeded":
                skipped.append({"task_id": task_id, "reason": "已完成"})
                continue
            if task.status == "queued" and _has_live_dispatch(task):
                skipped.append({"task_id": task_id, "reason": "已在队列排队"})
                continue
            if mode == "retry":
                if task.status not in {"created", "failed", "cancelled", "queued"}:
                    skipped.append({"task_id": task_id, "reason": f"状态不支持从头执行（{task.status}）"})
                    continue
                _clear_workspace_cache(_workspace(task_id))
                submit_mode = "retry"
            else:
                if task.status not in {"created", "failed", "cancelled", "paused", "queued"}:
                    skipped.append({"task_id": task_id, "reason": f"状态不支持继续（{task.status}）"})
                    continue
                submit_mode = "resume"
            try:
                if self._enqueue(task_id, submit_mode, force=True):
                    dispatched.append(task_id)
                else:
                    skipped.append({"task_id": task_id, "reason": "投递未生效（已有在途投递）"})
            except RuntimeError as exc:
                # Celery 不可用：整批都会失败，继续循环没有意义，直接收尾
                skipped.append({"task_id": task_id, "reason": f"投递失败：{exc}"})
                break
        _trace(
            f"批量投递 batch={batch_id[:8]} mode={mode} 选中={len(task_ids)} "
            f"已投递={len(dispatched)} 跳过={len(skipped)}"
        )
        return {
            "batch_id": batch_id,
            "mode": mode,
            "dispatched": dispatched,
            "skipped": skipped,
            "queue": self._queue_stats(),
        }

    def cancel_task(self, batch_id: str, task_id: str) -> dict:
        self._ensure_member(batch_id, task_id)
        task = request_cancel(task_id, "user_requested")
        return {"task_id": task_id, "status": task.status}

    def retry_task(self, batch_id: str, task_id: str) -> dict:
        task = self._ensure_member(batch_id, task_id)
        # running/stopping：真的在执行，重复操作视为幂等。
        if task.status in {"running", "stopping"}:
            return {"task_id": task_id, "status": task.status, "already_active": True}
        if task.status == "queued":
            # 僵尸排队（消息已丢失、从未被 worker 领走）允许从头执行；
            # 仍有在途投递证据时拒绝，避免清掉它正在使用的工作区缓存。
            if _has_live_dispatch(task):
                return {"task_id": task_id, "status": task.status, "already_active": True}
        elif task.status not in {"created", "failed", "cancelled"}:
            raise ValueError(f"Task {task_id} is not in a retriable state (status={task.status})")
        # 从头执行：清空 cache 中间产物，全新开始
        _clear_workspace_cache(_workspace(task_id))
        _trace(f"重跑任务 batch={batch_id[:8]} task={task_id[:8]}")
        dispatched = self._enqueue(task_id, "retry", force=True)
        return {"task_id": task_id, "status": "queued", "dispatched": dispatched}

    def resume_single_task(self, batch_id: str, task_id: str) -> dict:
        task = self._ensure_member(batch_id, task_id)
        # running/stopping：真的在执行，重复「继续」是幂等操作。
        if task.status in {"running", "stopping"}:
            return {"task_id": task_id, "status": task.status, "already_active": True}
        # queued 必须允许：批次视图把真实 queued 映射为 created 并渲染「继续」按钮
        # （见 WORKBENCH_TASK_STATUS），且 worker 重启复位后的任务正是 queued + 哨兵。
        # force=True 让僵尸排队（消息已丢失、一直停在 queued）也能被真正重新投递——
        # 否则单飞保护会静默返回，前端表现为「点继续没反应」；重复执行由 fencing 兜底。
        if task.status not in {"created", "failed", "cancelled", "paused", "queued"}:
            raise ValueError(f"Task {task_id} is not in a resumable state (status={task.status})")
        _trace(f"继续单任务 batch={batch_id[:8]} task={task_id[:8]}")
        dispatched = self._enqueue(task_id, "resume", force=True)
        return {"task_id": task_id, "status": "queued", "dispatched": dispatched}

    def delete_batch(self, batch_id: str) -> dict:
        self._signal_stop(batch_id)
        blocked = []
        for task in self._tasks_for_batch(batch_id):
            deleted = request_delete(task.id, "batch_deleted")
            if deleted is not None and deleted.status in {"running", "stopping"}:
                blocked.append(task.id)
        return {"batch_id": batch_id, "deleted": True, "blocked": blocked}

    def delete_tasks(self, batch_id: str, task_ids: list) -> dict:
        tasks = {task.id: task for task in self._tasks_for_batch(batch_id)}
        deleted = 0
        blocked = []
        for task_id in task_ids:
            if task_id not in tasks:
                continue
            result = request_delete(task_id, "batch_task_deleted")
            if result is not None and result.status in {"running", "stopping"}:
                blocked.append(task_id)
            else:
                deleted += 1
        return {"batch_id": batch_id, "deleted": deleted, "blocked": blocked, "remaining": len(tasks) - deleted - len(blocked)}

    def stop_all(self) -> dict:
        stopped = []
        for batch in self.list_batches():
            if batch["status"] in {"running", "paused"}:
                self.stop_batch(batch["id"])
                stopped.append(batch["id"])
        return {"stopped": stopped}

    def append_tasks(self, batch_id: str, tasks_input: list, common_config: Optional[dict] = None) -> dict:
        tasks = self._tasks_for_batch(batch_id)
        meta = _batch_meta(tasks[0])
        workflow = (tasks[0].payload or {}).get("workflow", {})
        common = common_config or {}
        _trace(f"追加任务到批次 batch={batch_id[:8]} count={len(tasks_input)}")
        for offset, raw_input in enumerate(tasks_input):
            input_config = {**common, **raw_input}
            index = len(tasks) + offset
            task_name = _derive_task_name(input_config) or f"task_{index + 1}"
            task_id = uuid.uuid4().hex
            task, _ = submit_workflow(workflow, input_config, mode="batch", task_id=task_id, enqueue=False, idempotency_scope=task_id)
            with session_scope() as session:
                stored = session.get(Task, task.id)
                stored.legacy_key = f"batch:{batch_id}:{stored.id}"
                stored.payload = {**stored.payload, "batch": {**meta, "task_name": task_name, "index": index}}
            workspace = _workspace(task.id)
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "workflow.json").write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
            _trace(f"批次 {batch_id[:8]} 追加任务 #{index + 1} task={task.id[:8]} name={task_name}")
        return {"batch_id": batch_id, "added": len(tasks_input), "total": len(tasks) + len(tasks_input)}

    def resume_unfinished(self, batch_id: str) -> dict:
        tasks = self._tasks_for_batch(batch_id)
        _trace(f"继续未完成任务 batch={batch_id[:8]} tasks={len(tasks)}")
        self._start_delivery(batch_id, "resume")
        return {**self.get_batch_detail(batch_id), "submitted": len(tasks)}

    def _ensure_member(self, batch_id: str, task_id: str) -> Task:
        tasks = {task.id: task for task in self._tasks_for_batch(batch_id)}
        if task_id not in tasks:
            raise FileNotFoundError(f"Task {task_id} not found in batch {batch_id}")
        return tasks[task_id]


def get_batch_executor():
    if not hasattr(get_batch_executor, "_instance"):
        get_batch_executor._instance = BatchExecutor()
    return get_batch_executor._instance
