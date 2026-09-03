import asyncio
import json
import threading
from collections import deque
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.voiceforge.database import session
from backend.voiceforge.task_defaults import synthesis_concurrency


router = APIRouter()


# ── 线程安全广播队列：worker 线程 → 事件循环 ──────────────────────────
# 与 backend/api/ws_queue.py 的广播模型一致：worker（Celery / 本地线程池）
# 把 project_id 投递到 deque，事件循环内的 drain 任务取出后主动推送快照。
_project_queue: deque[str] = deque()
_queue_lock = threading.Lock()
_drain_task = None

# 订阅某项目的 WebSocket 连接（仅在事件循环协程内增删，单线程无需加锁）
PROJECT_CONNECTIONS: dict[str, set[WebSocket]] = {}


def enqueue_project_progress(project_id: str) -> None:
    """worker 线程调用：请求向订阅该项目的前端推送一次最新进度快照。

    线程安全（deque + Lock）。若当前无订阅者，drain 阶段会直接跳过，几乎零开销。
    """
    if not project_id:
        return
    with _queue_lock:
        _project_queue.append(project_id)


async def _drain_project_queue() -> None:
    """事件循环内后台任务：批量取出 project_id 并主动广播最新快照。"""
    global _drain_task
    while True:
        try:
            batch = []
            with _queue_lock:
                while _project_queue:
                    batch.append(_project_queue.popleft())
            # 同一 drain 周期内重复的项目只推一次（始终读取最新 DB 状态）
            seen = set()
            for pid in batch:
                if pid not in seen:
                    seen.add(pid)
                    try:
                        await broadcast_project_progress(pid)
                    except Exception as e:
                        print(f"[voiceforge_ws] broadcast error for {pid}: {e}", flush=True)
        except Exception as e:
            print(f"[voiceforge_ws] drainer error: {e}", flush=True)
        await asyncio.sleep(0.05)


def start_project_drainer() -> None:
    """app 启动时在事件循环上启动 drain 任务（幂等）。"""
    global _drain_task
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running() and (_drain_task is None or _drain_task.done()):
            _drain_task = loop.create_task(_drain_project_queue())
    except RuntimeError:
        pass


def _parse_ts(value):
    if not value:
        return None
    # ISO 格式（update_task 写入 datetime.now(timezone.utc).isoformat()）
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        pass
    # SQLite CURRENT_TIMESTAMP 格式兜底
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _avg_sentence_seconds(conn) -> float | None:
    """最近成功合成句子的平均耗时（秒），用于估算剩余时间。

    样本不足（还没有成功句）时返回 None，由调用方决定 ETA 不可估。
    """
    rows = conn.execute(
        "SELECT started_at, finished_at FROM vf_tasks "
        "WHERE task_type='synthesize_sentence' AND status='succeeded' "
        "AND started_at IS NOT NULL AND finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT 50"
    ).fetchall()
    durations = []
    for r in rows:
        s, f = _parse_ts(r["started_at"]), _parse_ts(r["finished_at"])
        if s and f:
            d = (f - s).total_seconds()
            if d >= 0:
                durations.append(d)
    if not durations:
        return None
    return sum(durations) / len(durations)


def project_snapshot(project_id: str) -> dict:
    """项目级进度汇总：供 WebSocket 在状态变更时主动推送给前端做局部更新。

    包含：
    - summary：总进度、各状态计数、当前在途并发、并发上限、预计剩余时间(ETA)
    - sentences：全部句子的轻量状态（不含文本），前端据此局部更新行状态
    - tasks：任务列表，供任务面板实时刷新
    """
    with session() as conn:
        counts = conn.execute(
            "SELECT status, COUNT(*) AS c FROM vf_sentences WHERE project_id = ? GROUP BY status",
            (project_id,),
        ).fetchall()
        stat = {row["status"]: row["c"] for row in counts}
        total = sum(stat.values())
        done = stat.get("done", 0)
        generating = stat.get("generating", 0)
        queued = stat.get("queued", 0)
        error = stat.get("error", 0)

        # 当前在途合成任务（任务泵口径：running + 已投递排队），用于 ETA 与并发展示
        in_flight = conn.execute(
            "SELECT COUNT(*) AS c FROM vf_tasks WHERE task_type='synthesize_sentence' "
            "AND (status='running' OR (status='queued' AND dispatched=1))"
        ).fetchone()["c"]

        sentence_rows = conn.execute(
            "SELECT id, status, error_message, audio_storage_key, audio_duration "
            "FROM vf_sentences WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        sentences = [
            {
                "id": r["id"],
                "status": r["status"],
                "error_message": r["error_message"],
                "audio_storage_key": r["audio_storage_key"],
                "audio_duration": r["audio_duration"],
            }
            for r in sentence_rows
        ]

        task_rows = conn.execute(
            "SELECT id, task_type, status, progress, error_message, created_at, started_at, finished_at "
            "FROM vf_tasks WHERE project_id = ? ORDER BY created_at DESC LIMIT 200",
            (project_id,),
        ).fetchall()
        tasks = [dict(r) for r in task_rows]

        avg = _avg_sentence_seconds(conn)

    concurrency = synthesis_concurrency()
    progress_pct = round(done / total * 100) if total else 0

    # 预计剩余时间：剩余未完成句 / 当前并发在途 × 平均单句耗时
    pending = total - done
    eta = None
    if pending > 0 and in_flight > 0 and avg:
        eta = pending / in_flight * avg

    summary = {
        "total": total,
        "done": done,
        "generating": generating,
        "queued": queued,
        "error": error,
        "in_flight": in_flight,
        "concurrency": concurrency,
        "progress_pct": progress_pct,
        "eta_seconds": eta,
    }
    return {
        "type": "voiceforge.progress",
        "project_id": project_id,
        "summary": summary,
        "sentences": sentences,
        "tasks": tasks,
    }


async def broadcast_project_progress(project_id: str) -> None:
    """把某项目的最新快照推送给所有订阅的前端连接。"""
    conns = PROJECT_CONNECTIONS.get(project_id)
    if not conns:
        return
    try:
        encoded = json.dumps(project_snapshot(project_id), ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        return
    dead = []
    for ws in list(conns):
        try:
            await ws.send_text(encoded)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.discard(ws)
    if not conns:
        PROJECT_CONNECTIONS.pop(project_id, None)


@router.websocket("/projects/{project_id}/progress")
async def project_progress(websocket: WebSocket, project_id: str):
    await websocket.accept()
    PROJECT_CONNECTIONS.setdefault(project_id, set()).add(websocket)
    # 连接即推送当前快照（首屏无需等待首次事件）
    try:
        await websocket.send_text(
            json.dumps(project_snapshot(project_id), ensure_ascii=False, default=str, sort_keys=True)
        )
    except Exception:
        pass
    # 事件驱动：不再轮询 DB，仅在状态变更经广播队列触发时推送；
    # receive_text 仅用于保持连接存活，直到客户端断开
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        conns = PROJECT_CONNECTIONS.get(project_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                PROJECT_CONNECTIONS.pop(project_id, None)


@router.websocket("/voices/{voice_id}/progress")
async def voice_progress(websocket: WebSocket, voice_id: str):
    await websocket.accept()
    previous = None
    try:
        while True:
            with session() as conn:
                tasks = conn.execute(
                    "SELECT id, task_type, status, progress, error_message, output_json FROM vf_tasks WHERE voice_id = ? ORDER BY created_at DESC LIMIT 100",
                    (voice_id,),
                ).fetchall()
            task_items = []
            for item in tasks:
                value = dict(item)
                value["output"] = json.loads(value.pop("output_json") or "{}")
                task_items.append(value)
            snapshot = {"type": "voiceforge.voice_progress", "voice_id": voice_id, "tasks": task_items}
            encoded = json.dumps(snapshot, ensure_ascii=False, default=str, sort_keys=True)
            if encoded != previous:
                await websocket.send_text(encoded)
                previous = encoded
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
