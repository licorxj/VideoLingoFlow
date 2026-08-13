"""WebSocket API: real-time task progress."""
import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# Connected clients per task
_connections: dict[str, list[WebSocket]] = {}


async def _push_current_state(websocket: WebSocket, task_id: str):
    return 0


def _event_payload(event):
    payload = {"task_id": event.task_id, "event_id": event.id, "event_sequence": event.event_sequence, "event_type": event.event_type, "correlation_id": event.correlation_id}
    payload.update(event.payload or {})
    return payload


async def _send_persisted_events(websocket: WebSocket, task_id: str, sequence: int) -> int:
    from backend.control_plane.database import session_scope
    from backend.control_plane.repository import read_task_events
    with session_scope() as session:
        events = read_task_events(session, task_id, sequence, 100)
    for event in events:
        await websocket.send_json(_event_payload(event))
        sequence = event.event_sequence
    return sequence


@router.websocket("/tasks/{task_id}")
async def task_ws(websocket: WebSocket, task_id: str):
    await websocket.accept()
    if task_id not in _connections:
        _connections[task_id] = []
    _connections[task_id].append(websocket)
    sequence = await _send_persisted_events(websocket, task_id, 0)
    try:
        while True:
            poll = asyncio.create_task(_send_persisted_events(websocket, task_id, sequence))
            receive = asyncio.create_task(websocket.receive_text())
            done, pending = await asyncio.wait({poll, receive}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            # 消费两个任务的结果与异常，避免 "Task exception was never retrieved"
            # （客户端断开时 receive_text/send_json 会抛 WebSocketDisconnect 或
            # RuntimeError("WebSocket is not connected")，统一按断开处理）
            disconnected = False
            if poll in done:
                try:
                    sequence = poll.result()
                except (WebSocketDisconnect, RuntimeError):
                    disconnected = True
            if receive in done:
                try:
                    receive.result()
                except (WebSocketDisconnect, RuntimeError):
                    disconnected = True
            if disconnected:
                break
            await asyncio.sleep(0.25)
    except WebSocketDisconnect:
        pass
    finally:
        if task_id in _connections:
            try:
                _connections[task_id].remove(websocket)
            except ValueError:
                pass
            if not _connections[task_id]:
                del _connections[task_id]


async def broadcast_progress(task_id: str, step_id: str, progress: int, message: str, extra: dict | None = None):
    """Send progress update to all connected clients for a task."""
    if task_id not in _connections:
        return
    payload_data = {
        "task_id": task_id,
        "step_id": step_id,
        "progress": progress,
        "message": message,
    }
    if extra:
        payload_data.update(extra)
    payload = json.dumps(payload_data)
    dead = []
    for ws in _connections[task_id]:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections[task_id].remove(ws)
    from backend.api.collaboration_ws import forward_progress
    forward_progress(payload_data)


def get_ws_callback():
    """Returns a sync callback that can be called from thread pool."""
    import asyncio
    def callback(task_id, step_id, progress, message, extra=None):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(broadcast_progress(task_id, step_id, progress, message, extra))
        except RuntimeError:
            pass
    return callback
