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
from backend.control_plane.workflow_runtime import _node_type, _resource_for, _workspace, _write_legacy_task, queue_for, request_cancel, request_delete, submit_workflow, _clear_workspace_cache


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted"}
# 批次视图排除的状态：已删除与删除中断残留（历史遗留的 stuck deleting 记录）
# 不应再出现在批量页面，否则删除后条目仍显示（表现为"删除无效"）。
BATCH_HIDDEN_STATUSES = {"deleted", "deleting"}
WORKBENCH_TASK_STATUS = {
    "succeeded": "completed",
    "queued": "created",
    "stopping": "running",
    "deleted": "cancelled",
    "deleting": "cancelled",
}
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


def _batch_meta(task: Task) -> dict:
    return (task.payload or {}).get("batch", {})


def _workbench_task_status(status: str) -> str:
    return WORKBENCH_TASK_STATUS.get(status, status)


def _workbench_node_status(status: str) -> str:
    return WORKBENCH_NODE_STATUS.get(status, status)


def _task_payload(task: Task) -> dict:
    payload = task.payload or {}
    meta = _batch_meta(task)
    return {
        "task_id": task.id,
        "task_name": meta.get("task_name", task.id),
        "status": _workbench_task_status(task.status),
        "index": meta.get("index", 0),
        "input": payload.get("input", {}),
        "nodes": {
            node.node_key: {
                "nodeType": (node.payload or {}).get("data", {}).get("nodeType", ""),
                "label": (node.payload or {}).get("data", {}).get("label", ""),
                "status": _workbench_node_status(node.status),
                "progress": 100 if node.status == "succeeded" else 0,
                # 失败节点优先返回真实错误信息（payload.message），回退错误分类
                "message": (node.payload or {}).get("message", "") if node.status == "failed" else "",
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
    statuses = [task.status for task in tasks]
    if not statuses:
        return "created"
    if all(status == "succeeded" for status in statuses):
        return "completed"
    if all(status in TERMINAL_STATUSES for status in statuses):
        return "partial" if "succeeded" in statuses else "failed"
    if any(status == "running" for status in statuses):
        return "running"
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
            return
        # 新投递轮次：清掉旧停止信号，重新计数
        self._stop_events.pop(batch_id, None)
        thread = threading.Thread(target=self._deliver_loop, args=(batch_id, mode), daemon=True, name=f"batch-deliver-{batch_id[:8]}")
        self._delivery_threads[batch_id] = thread
        thread.start()

    def _deliver_loop(self, batch_id: str, mode: str) -> None:
        """后台投递循环：按 max_concurrent_tasks 限流 + task_start_interval 间隔，可被停止信号中止。"""
        evt = self._stop_event(batch_id)
        max_concurrent = max(1, self._get_max_workers())
        interval = max(0.0, float(config.get("batch.task_start_interval", 0)))
        # 统计当前批次所有任务的投递顺序（按创建时间）
        with session_scope() as session:
            order = [task.id for task in session.scalars(select(Task).where(Task.legacy_key.like(f"batch:{batch_id}:%")).order_by(Task.created_at)).all()]
        try:
            for task_id in order:
                if evt.is_set():
                    break
                # 并行数量限流：该批次活跃（queued/running/stopping）任务数 >= max_concurrent 时等待
                while not evt.is_set() and self._active_count(batch_id) >= max_concurrent:
                    time.sleep(0.5)
                if evt.is_set():
                    break
                # 跳过已在队列/运行/成功/已删除的任务
                with session_scope() as session:
                    task = session.get(Task, task_id)
                    if task is None or task.status in {"queued", "running", "succeeded", "deleted"}:
                        continue
                try:
                    self._enqueue(task_id, mode)
                except RuntimeError:
                    break  # Celery 不可用等，停止投递
                # 启动间隔（分段 sleep，期间响应停止信号）
                slept = 0.0
                while slept < interval and not evt.is_set():
                    step = min(0.2, interval - slept)
                    time.sleep(step)
                    slept += step
        finally:
            self._delivery_threads.pop(batch_id, None)

    def _active_count(self, batch_id: str) -> int:
        with session_scope() as session:
            return sum(1 for task in session.scalars(select(Task).where(Task.legacy_key.like(f"batch:{batch_id}:%"))).all() if task.status in {"queued", "running", "stopping"})

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
        return {"batch_id": batch_id, "batch_name": name, "task_count": len(tasks_input), "status": "created"}

    def list_batches(self) -> list:
        with session_scope() as session:
            tasks = session.scalars(select(Task).options(selectinload(Task.nodes)).where(
                Task.legacy_key.like("batch:%"),
                Task.status.notin_(BATCH_HIDDEN_STATUSES),
            ).order_by(Task.created_at.desc())).unique().all()
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

    def _enqueue(self, task_id: str, mode: str = "new") -> None:
        with session_scope() as session:
            task = session.get(Task, task_id)
            if task is None:
                return
            workflow = (task.payload or {}).get("workflow", {})
            input_config = (task.payload or {}).get("input", {})
        submit_workflow(workflow, input_config, mode=mode, task_id=task_id, enqueue=True, idempotency_scope=task_id)

    def start_batch(self, batch_id: str) -> dict:
        tasks = self._tasks_for_batch(batch_id)
        self._start_delivery(batch_id, "batch")
        return {"batch_id": batch_id, "status": "running", "task_count": len(tasks), "submitted": len(tasks)}

    def stop_batch(self, batch_id: str) -> dict:
        self._signal_stop(batch_id)
        for task in self._tasks_for_batch(batch_id):
            request_cancel(task.id, "batch_stopped")
        return {"batch_id": batch_id, "status": "stopped"}

    def sync_workflow(self, batch_id: str, workflow_id: str = "") -> dict:
        tasks = self._tasks_for_batch(batch_id)
        active_task_ids = [task.id for task in tasks if task.status in {"queued", "running", "stopping"}]
        if active_task_ids:
            raise RuntimeError(f"批次存在执行中的任务，无法同步工作流: {', '.join(active_task_ids)}")
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
                    resource = _resource_for(node_type)
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
                workspace = _workspace(task.id)
                workspace.mkdir(parents=True, exist_ok=True)
                (workspace / "workflow.json").write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
                session.flush()
                _write_legacy_task(task, workspace)
        return {"batch_id": batch_id, "workflow_id": workflow_id, "synced": True}

    def cancel_task(self, batch_id: str, task_id: str) -> dict:
        self._ensure_member(batch_id, task_id)
        task = request_cancel(task_id, "user_requested")
        return {"task_id": task_id, "status": task.status}

    def retry_task(self, batch_id: str, task_id: str) -> dict:
        task = self._ensure_member(batch_id, task_id)
        if task.status not in {"created", "failed", "cancelled"}:
            raise ValueError(f"Task {task_id} is not in a retriable state (status={task.status})")
        # 从头执行：清空 cache 中间产物，全新开始
        _clear_workspace_cache(_workspace(task_id))
        self._enqueue(task_id, "retry")
        return {"task_id": task_id, "status": "queued"}

    def resume_single_task(self, batch_id: str, task_id: str) -> dict:
        task = self._ensure_member(batch_id, task_id)
        if task.status not in {"created", "failed", "cancelled", "paused"}:
            raise ValueError(f"Task {task_id} is not in a resumable state (status={task.status})")
        self._enqueue(task_id, "resume")
        return {"task_id": task_id, "status": "queued"}

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
        return {"batch_id": batch_id, "added": len(tasks_input), "total": len(tasks) + len(tasks_input)}

    def resume_unfinished(self, batch_id: str) -> dict:
        tasks = self._tasks_for_batch(batch_id)
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
