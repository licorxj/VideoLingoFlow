from __future__ import annotations

from pathlib import Path
import asyncio
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend.control_plane.database import session_scope
from backend.control_plane.models import Task
from backend.editor.models import CharactersWriteRequest, ImportRequest, ProjectWriteRequest
from backend.editor.repository import TASKS_ROOT, EditorProjectRepository, RevisionConflictError


router = APIRouter()
repository = EditorProjectRepository()

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted"}


def _iter_workspace_roots() -> list[Path]:
    control_root = Path(os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", Path.cwd() / "control_plane_workspaces"))
    return [control_root, Path(TASKS_ROOT)]


def _clear_pending_edit(task_id: str) -> None:
    """用户在剪辑台保存项目后清除「待剪辑」标记。"""
    try:
        repository.task_dir(task_id)
    except HTTPException:
        return
    state_path = repository.editor_dir(task_id) / "push_state.json"
    if not state_path.is_file():
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["pendingEdit"] = False
        state["editedAt"] = datetime.now(timezone.utc).isoformat()
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass


@router.get("/tasks/pending")
async def list_pending_edit_tasks():
    """列出已推送到剪辑台、等待人工剪辑的任务（剪辑台首页「待剪辑」标签）。"""
    pending: list[dict] = []
    seen: set[str] = set()
    for root in _iter_workspace_roots():
        if not root.is_dir():
            continue
        for state_path in root.glob("*/editor/push_state.json"):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not state.get("pendingEdit"):
                continue
            task_id = str(state.get("taskId") or state_path.parent.parent.name)
            if task_id in seen:
                continue
            seen.add(task_id)
            task_dir = state_path.parent.parent
            task_name = task_id
            task_json = task_dir / "task.json"
            if task_json.is_file():
                try:
                    data = json.loads(task_json.read_text(encoding="utf-8"))
                    task_name = data.get("task_name") or task_id
                except (OSError, json.JSONDecodeError):
                    pass
            pending.append({
                "id": task_id,
                "task_name": task_name,
                "pushed_at": state.get("pushedAt"),
            })
    pending.sort(key=lambda item: str(item.get("pushed_at") or ""), reverse=True)
    return {"tasks": pending}


@router.get("/tasks")
async def list_editor_tasks():
    tasks = []
    with session_scope() as session:
        for task in session.query(Task).all():
            if task.status not in TERMINAL_STATUSES:
                continue
            payload = task.payload or {}
            batch = payload.get("batch", {}) or {}
            task_name = batch.get("task_name") or task.id
            if task_name == task.id:
                input_config = payload.get("input", {}) or {}
                for key in ("videoPath", "audioPath", "subtitlePath"):
                    value = input_config.get(key)
                    if value:
                        task_name = Path(value).stem
                        break
            try:
                has_project = repository.project_path(task.id).is_file()
            except HTTPException:
                has_project = False
            tasks.append({
                "id": task.id,
                "task_name": task_name,
                "status": task.status,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "finished_at": task.updated_at.isoformat() if task.status in TERMINAL_STATUSES and task.updated_at else None,
                "has_project": has_project,
            })
    return {"tasks": tasks}


@router.get("/tasks/{task_id}/import-candidates")
async def get_import_candidates(task_id: str):
    return {"candidates": [candidate.dict() for candidate in repository.import_candidates(task_id)]}


@router.post("/tasks/{task_id}/import")
async def import_task_assets(task_id: str, request: ImportRequest):
    return repository.import_assets(
        task_id,
        request.candidate_ids,
        request.use_dub_segments,
    )


@router.get("/tasks/{task_id}/project")
async def get_project(task_id: str):
    return repository.snapshot(task_id)


@router.put("/tasks/{task_id}/project")
async def update_project(task_id: str, request: ProjectWriteRequest):
    try:
        result = repository.save_project(task_id, request.project, request.expected_revision, "editor")
    except RevisionConflictError as exc:
        return JSONResponse(status_code=409, content={"detail": "revision_conflict", "revision": exc.revision})
    _clear_pending_edit(task_id)
    return result


@router.get("/tasks/{task_id}/assets/{asset_id}/stream")
async def stream_asset(task_id: str, asset_id: str):
    path = repository.asset_path(task_id, asset_id)
    return FileResponse(path, media_type=None, filename=path.name)


@router.get("/tasks/{task_id}/characters")
async def get_characters(task_id: str):
    snapshot = repository.snapshot(task_id)
    return {"characters": snapshot["characters"]}


@router.put("/tasks/{task_id}/characters")
async def update_characters(task_id: str, request: CharactersWriteRequest):
    try:
        return repository.save_characters(task_id, request.characters, request.expected_revision)
    except RevisionConflictError as exc:
        return JSONResponse(status_code=409, content={"detail": "revision_conflict", "revision": exc.revision})


@router.post("/tasks/{task_id}/exports")
async def upload_export(task_id: str, file: UploadFile = File(...), extension: str = Form(".mp4")):
    if extension.lower() not in {".mp4", ".webm"}:
        raise HTTPException(400, "Unsupported export format")
    destination = repository.export_path(task_id, extension)
    total = 0
    limit = 4 * 1024 * 1024 * 1024
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, "Export file is too large")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "Export file is empty")
    asset = repository.register_export(task_id, destination)
    return {"asset": asset.dict(), "path": str(destination), "resumed": False}
