"""Collaboration WebSocket channel: member presence, editing state and task progress relay."""
import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from backend.control_plane.database import session_scope
from backend.control_plane.models import User
from backend.control_plane.security import _utc, roles_for, ws_user_from_request

router = APIRouter()

HEARTBEAT_TIMEOUT = 30  # seconds without ping -> offline
PRESENCE_INTERVAL = 10  # seconds between presence sweeps
LAST_SEEN_DB_THROTTLE = 60  # seconds between DB writes of last_seen_at

# user_id -> {"websocket", "editing", "last_seen", "_last_db"}
_clients: dict[str, dict] = {}
_sweep_task: asyncio.Task | None = None


def online_user_ids() -> set[str]:
    return set(_clients)


def editing_for(user_id: str):
    client = _clients.get(user_id)
    return client["editing"] if client else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _presence_snapshot() -> list[dict]:
    now = _utc_now()
    with session_scope() as db:
        users = db.scalars(select(User).order_by(User.username)).all()
        members = []
        for item in users:
            client = _clients.get(item.id)
            online = client is not None or (item.last_seen_at is not None and (_utc(item.last_seen_at) - now).total_seconds() > -60)
            members.append({
                "user_id": item.id, "username": item.username, "display_name": item.display_name,
                "roles": sorted(roles_for(db, item.id)), "online": online,
                "last_seen_at": item.last_seen_at, "editing": client["editing"] if client else None,
            })
        return members


def _touch_last_seen(user_id: str) -> None:
    client = _clients.get(user_id)
    if not client:
        return
    now = _utc_now()
    if client.get("_last_db") and (now - client["_last_db"]).total_seconds() < LAST_SEEN_DB_THROTTLE:
        return
    client["_last_db"] = now
    with session_scope() as db:
        db.execute(update(User).where(User.id == user_id).values(last_seen_at=now))


async def _broadcast(payload: dict) -> None:
    dead = []
    for user_id, client in list(_clients.items()):
        try:
            await client["websocket"].send_text(json.dumps(payload, default=str))
        except Exception:
            dead.append(user_id)
    for user_id in dead:
        _clients.pop(user_id, None)


async def _broadcast_presence() -> None:
    await _broadcast({"type": "presence", "members": _presence_snapshot()})


async def _sweep_loop() -> None:
    while True:
        await asyncio.sleep(PRESENCE_INTERVAL)
        now = _utc_now()
        stale = [uid for uid, client in _clients.items() if (now - client["last_seen"]).total_seconds() > HEARTBEAT_TIMEOUT]
        changed = False
        for uid in stale:
            if _clients.pop(uid, None):
                changed = True
        if changed:
            await _broadcast_presence()


def forward_progress(payload: dict) -> None:
    """Relay a task progress payload to all connected collaboration clients (sync, thread-safe)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_broadcast({"type": "progress", **payload}))
    except RuntimeError:
        pass


async def _handle_message(user_id: str, raw: str, websocket: WebSocket) -> None:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return
    mtype = message.get("type")
    if mtype == "ping":
        client = _clients.get(user_id)
        if client:
            client["last_seen"] = _utc_now()
            _touch_last_seen(user_id)
        await websocket.send_text(json.dumps({"type": "pong"}))
    elif mtype == "editing":
        client = _clients.get(user_id)
        if client:
            editing = message.get("editing")
            client["editing"] = editing
            await _broadcast({"type": "editing", "user_id": user_id, "editing": editing})


@router.websocket("/collaboration")
async def collaboration_ws(websocket: WebSocket):
    user = await ws_user_from_request(websocket)
    if user is None:
        return
    await websocket.accept()
    global _sweep_task
    if _sweep_task is None or _sweep_task.done():
        _sweep_task = asyncio.create_task(_sweep_loop())
    user_id = user.id
    previous = _clients.get(user_id)
    _clients[user_id] = {
        "websocket": websocket,
        "editing": previous["editing"] if previous else None,
        "last_seen": _utc_now(),
        "_last_db": _utc_now(),
    }
    with session_scope() as db:
        db.execute(update(User).where(User.id == user_id).values(last_seen_at=_utc_now()))
    await _broadcast_presence()
    try:
        while True:
            message = await websocket.receive_text()
            await _handle_message(user_id, message, websocket)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if _clients.get(user_id, {}).get("websocket") is websocket:
            _clients.pop(user_id, None)
        await _broadcast_presence()
