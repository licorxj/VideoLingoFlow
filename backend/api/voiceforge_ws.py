import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.voiceforge.database import session


router = APIRouter()


def project_snapshot(project_id: str):
    with session() as conn:
        tasks = conn.execute(
            "SELECT id, task_type, status, progress, error_message, created_at, started_at, finished_at FROM vf_tasks WHERE project_id = ? ORDER BY created_at DESC LIMIT 100",
            (project_id,),
        ).fetchall()
        sentences = conn.execute(
            "SELECT id, status, task_id, error_message FROM vf_sentences WHERE project_id = ? AND status IN ('queued', 'generating', 'error') ORDER BY order_index",
            (project_id,),
        ).fetchall()
    return {"type": "voiceforge.progress", "project_id": project_id, "tasks": [dict(item) for item in tasks], "active_sentences": [dict(item) for item in sentences]}


@router.websocket("/projects/{project_id}/progress")
async def project_progress(websocket: WebSocket, project_id: str):
    await websocket.accept()
    previous = None
    try:
        while True:
            snapshot = project_snapshot(project_id)
            encoded = json.dumps(snapshot, ensure_ascii=False, default=str, sort_keys=True)
            if encoded != previous:
                await websocket.send_text(encoded)
                previous = encoded
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


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
