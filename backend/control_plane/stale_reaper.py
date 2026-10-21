"""控制平面 stale 任务周期回收（API 进程守护线程）。

背景：任务可能因 worker 崩溃 / Redis 丢消息 / Celery 硬超时杀进程而永远停在
queued/running——旧逻辑只在 worker 重启时复位一次（worker_ready 钩子），
worker 不再重启时前端无限转圈且无法恢复。

本模块在 API 进程内每 60s 扫描一次：
- queued 僵尸：dispatch_token 为 DISPATCH_STALE（投递时 Redis/Celery 不可用），
  或投递时间超过 CONTROL_PLANE_STALE_QUEUED_MINUTES（默认 120min）；
- running 卡死：存在 started_at 超过 CONTROL_PLANE_STALE_RUNNING_MINUTES
  （默认 90min）的 running 节点。节点自带 3600s 超时、Celery 硬杀 3600s，
  健康节点不可能超过 60min，故 90min 阈值不会误伤。

处理语义：任务置 interrupted（running）或 cancelled（queued，dispatch_lost），
节点复位 pending（复用 workflow_runtime._reset_task_nodes_to_pending，含
dispatch 哨兵），用户可一键重跑/继续。只改 DB 状态，不杀进程——真正在跑的
由 worker/Celery 时限处理，避免 PID 复用误杀。
"""
import os
import threading
import time

from rich.console import Console

console = Console()

REAP_INTERVAL_SECONDS = 60.0


def _env_minutes(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return default


def _stale_queued_minutes() -> float:
    return _env_minutes("CONTROL_PLANE_STALE_QUEUED_MINUTES", 120.0)


def _stale_running_minutes() -> float:
    return _env_minutes("CONTROL_PLANE_STALE_RUNNING_MINUTES", 90.0)


def _node_started_at(node) -> float:
    payload = node.payload or {}
    timings = payload.get("timings") or {}
    value = timings.get("started_at")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return 0.0


def reap_once() -> dict:
    """扫描一轮，返回处理摘要（dry 信息仅供日志/测试）。"""
    from sqlalchemy import select

    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task, TaskNode
    from backend.control_plane.workflow_runtime import (
        DISPATCH_STALE,
        _reset_task_nodes_to_pending,
        _set_task,
    )
    from backend.control_plane.runtime import InvalidTransition

    summary = {"queued": 0, "running": 0, "task_ids": []}
    now = time.time()
    queued_cutoff = now - _stale_queued_minutes() * 60
    running_cutoff = now - _stale_running_minutes() * 60
    with session_scope() as session:
        # ① queued 僵尸：投递失败哨兵或投递超龄（worker 不在/消息丢失）
        for task in session.scalars(select(Task).where(Task.status == "queued")).all():
            if task.deletion_requested:
                continue
            payload = task.payload or {}
            dispatched_at = payload.get("dispatch_token_at")
            if not isinstance(dispatched_at, (int, float)) or dispatched_at <= 0:
                dispatched_at = task.created_at.timestamp() if task.created_at else now
            stale = payload.get("dispatch_token") == DISPATCH_STALE or dispatched_at < queued_cutoff
            if not stale:
                continue
            try:
                _set_task(session, task, "cancelled", cancel_reason="dispatch_lost")
            except InvalidTransition:
                continue
            _reset_task_nodes_to_pending(session, task, "dispatch_lost")
            summary["queued"] += 1
            summary["task_ids"].append(task.id)
        # ② running 卡死：节点 started_at 超龄（worker 被硬杀/崩溃的典型残留）
        for task in session.scalars(select(Task).where(Task.status == "running")).all():
            if task.deletion_requested:
                continue
            running_nodes = [n for n in task.nodes if n.status == "running"]
            if not running_nodes:
                continue
            oldest = min(
                (_node_started_at(n) for n in running_nodes),
                default=0.0,
            )
            if oldest <= 0:
                # 无 timings 的老任务：退回任务行更新时间判断
                oldest = task.updated_at.timestamp() if task.updated_at else now
            if oldest >= running_cutoff:
                continue
            try:
                _set_task(session, task, "interrupted", cancel_reason="stale_running")
            except InvalidTransition:
                continue
            _reset_task_nodes_to_pending(session, task, "stale_running")
            summary["running"] += 1
            summary["task_ids"].append(task.id)
    if summary["queued"] or summary["running"]:
        console.log(
            f"[cyan]stale 回收：queued 僵尸 {summary['queued']} 个 / running 卡死 "
            f"{summary['running']} 个（已置 interrupted/cancelled，可重跑）[/cyan]"
        )
    return summary


_reaper_stop = threading.Event()
_reaper_thread: threading.Thread | None = None


def _loop() -> None:
    while not _reaper_stop.wait(REAP_INTERVAL_SECONDS):
        try:
            reap_once()
        except Exception as exc:  # noqa: BLE001 - 守护线程不允任何异常退出循环
            console.log(f"[yellow]stale 回收扫描失败（下轮重试）: {exc}[/yellow]")


def start_stale_reaper() -> bool:
    """启动周期回收守护线程（幂等）。CONTROL_PLANE_REAPER=0 关闭（默认开）。"""
    if os.getenv("CONTROL_PLANE_REAPER", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    global _reaper_thread
    if _reaper_thread is not None and _reaper_thread.is_alive():
        return True
    _reaper_stop.clear()
    _reaper_thread = threading.Thread(target=_loop, name="stale-task-reaper", daemon=True)
    _reaper_thread.start()
    return True


def stop_stale_reaper() -> None:
    _reaper_stop.set()
