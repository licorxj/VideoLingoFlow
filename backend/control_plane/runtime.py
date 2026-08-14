import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterator

from filelock import FileLock, Timeout as FileLockTimeout


class TaskStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DELETING = "deleting"
    DELETED = "deleted"


class NodeStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TASK_TERMINAL_STATES = {TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value, TaskStatus.DELETED.value}
NODE_TERMINAL_STATES = {item.value for item in (NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.CANCELLED)}

TASK_TRANSITIONS = {
    "created": {"queued", "running", "cancelled", "deleting"},
    "queued": {"running", "cancelled", "deleting"},
    "running": {"queued", "paused", "stopping", "succeeded", "failed", "cancelled", "deleting"},
    "paused": {"queued", "running", "cancelled", "deleting"},
    "stopping": {"cancelled", "failed", "deleting"},
    "succeeded": {"queued", "deleting"},
    "failed": {"queued", "deleting"},
    "cancelled": {"queued", "deleting"},
    "deleting": {"deleted", "failed"},
    "deleted": {"queued"},
}

NODE_TRANSITIONS = {
    "pending": {"queued", "running", "cancelled"},
    "queued": {"running", "cancelled", "interrupted"},
    "running": {"paused", "succeeded", "failed", "cancelled", "interrupted"},
    "paused": {"queued", "running", "cancelled"},
    "interrupted": {"queued", "running", "cancelled", "failed"},
    "succeeded": set(),
    "failed": {"queued"},
    "cancelled": {"queued"},
}


class InvalidTransition(ValueError):
    pass


class RetryableTaskError(RuntimeError):
    pass


class PermanentTaskError(RuntimeError):
    pass


class TaskTimeoutError(TimeoutError):
    pass


class TaskCancelledError(RuntimeError):
    pass


class WorkflowWaitingError(RuntimeError):
    def __init__(self, message: str, workbench_url: str):
        self.workbench_url = workbench_url
        super().__init__(message)


def transition(current: str, target: str, node: bool = False) -> str:
    transitions = NODE_TRANSITIONS if node else TASK_TRANSITIONS
    if target not in transitions.get(current, set()):
        raise InvalidTransition(f"不允许状态转换: {current} -> {target}")
    return target


def idempotency_key(task_type: str, payload: dict, namespace: str = "workflow") -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"{namespace}:{task_type}:{digest}"


def classify_error(exc: BaseException) -> str:
    if isinstance(exc, TaskCancelledError):
        return "cancelled"
    if isinstance(exc, TaskTimeoutError) or isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, (RetryableTaskError, ConnectionError)):
        return "retryable"
    if isinstance(exc, OSError):
        # 文件缺失/权限等确定性错误重试无意义（ConnectionError 已在上方归类为 retryable）
        return "permanent"
    return "permanent"


@dataclass
class CancellationToken:
    task_id: str
    reason: str = ""
    _cancelled: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def cancel(self, reason: str) -> None:
        with self._lock:
            self._cancelled = True
            self.reason = reason or "user_requested"

    def checkpoint(self) -> None:
        with self._lock:
            if self._cancelled:
                raise TaskCancelledError(self.reason or "user_requested")


@contextmanager
def execution_checkpoint(token: CancellationToken, save: Callable[[dict], None] | None = None, state: dict | None = None) -> Iterator[dict]:
    checkpoint = state if state is not None else {}
    token.checkpoint()
    try:
        yield checkpoint
        token.checkpoint()
        if save:
            save(checkpoint)
    except TaskCancelledError:
        if save:
            save({**checkpoint, "interrupted": True, "cancel_reason": token.reason})
        raise


class ResourceLimitError(RetryableTaskError):
    pass


class ResourceTokens:
    def __init__(self, capacities: dict[str, int] | None = None, redis_client=None, prefix: str = "videolingo:resource"):
        self.capacities = capacities or {"cpu": 1, "gpu": 1, "llm": 4, "tts": 2, "io": 4}
        self.redis = redis_client
        self.prefix = prefix
        self._local = {resource: threading.BoundedSemaphore(capacity) for resource, capacity in self.capacities.items()}

    @staticmethod
    def _gpu_lock_path() -> str:
        configured = os.getenv("CONTROL_PLANE_GPU_LOCK_PATH")
        if configured:
            return configured
        root = os.getenv("CONTROL_PLANE_DATA_ROOT") or os.getenv("CONTROL_PLANE_WORKSPACE_ROOT") or str(os.getcwd())
        lock_path = os.path.join(root, "locks", "gpu.lock")
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        return lock_path

    @contextmanager
    def acquire(self, resource: str, timeout: float | None = None) -> Iterator[None]:
        capacity = self.capacities.get(resource, 1)
        token_key = f"{self.prefix}:{resource}"
        acquired = False
        if self.redis is not None:
            deadline = time.monotonic() + (timeout if timeout is not None else 0)
            while True:
                value = self.redis.incr(token_key)
                if value <= capacity:
                    acquired = True
                    break
                self.redis.decr(token_key)
                if timeout is None or time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
        else:
            semaphore = self._local.setdefault(resource, threading.BoundedSemaphore(capacity))
            acquired = semaphore.acquire(timeout=timeout if timeout is not None else 0)
        if not acquired:
            raise ResourceLimitError(f"资源令牌不足: {resource}")
        gpu_lock = None
        if resource == "gpu":
            lock_path = self._gpu_lock_path()
            os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
            gpu_lock = FileLock(lock_path)
            try:
                gpu_lock.acquire(timeout=timeout if timeout is not None else 0)
            except FileLockTimeout as exc:
                if self.redis is not None:
                    self.redis.decr(token_key)
                else:
                    semaphore.release()
                raise ResourceLimitError("本机 GPU 正在执行其他重任务") from exc
        try:
            yield
        finally:
            if gpu_lock is not None:
                gpu_lock.release()
            if self.redis is not None:
                self.redis.decr(token_key)
            else:
                semaphore.release()


def queue_for(resource: str, capabilities: set[str] | None = None) -> str:
    if capabilities and resource not in capabilities:
        raise ValueError(f"worker 不具备资源能力: {resource}")
    # 网络请求型节点无资源类型（None）时归入 io 队列
    if not resource:
        resource = "io"
    return os.getenv(f"CELERY_QUEUE_{resource.upper()}", f"videolingo_{resource}")


def worker_id() -> str:
    return os.getenv("WORKER_ID") or f"worker-{uuid.uuid4().hex[:12]}"


def kill_process_tree(pid: int | None) -> bool:
    """强制终止进程树（子进程隔离的硬停止）。

    Windows 用 ``taskkill /F /T /PID`` 连子进程（如 ffmpeg）一起杀；
    其他平台对进程组发 SIGKILL。返回是否成功发起终止。
    """
    if not pid or pid <= 0:
        return False
    try:
        if os.name == "nt":
            import subprocess
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=15,
            )
        else:
            import signal
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)
        return True
    except Exception:
        return False
