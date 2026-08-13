from __future__ import annotations

from pathlib import Path
import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from backend.control_plane.database import session_scope
from backend.control_plane.models import Task
from backend.editor.models import CharactersWriteRequest, ImportRequest, ProjectWriteRequest
from backend.editor.repository import EditorProjectRepository, RevisionConflictError


router = APIRouter()
repository = EditorProjectRepository()

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted"}


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
        return repository.save_project(task_id, request.project, request.expected_revision, "editor")
    except RevisionConflictError as exc:
        return JSONResponse(status_code=409, content={"detail": "revision_conflict", "revision": exc.revision})


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
