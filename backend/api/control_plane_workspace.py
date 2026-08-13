"""Control plane task workspace file browsing & download (member-facing, project-scoped)."""
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from backend.control_plane.database import session_scope
from backend.control_plane.models import Task
from backend.control_plane.security import current_user, project_access

router = APIRouter()


def workspace_root() -> Path:
    return Path(os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", Path.cwd() / "control_plane_workspaces"))


def _task_in_project(db, task_id: str, project_id: str) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
    if not task:
        raise HTTPException(404, detail={"code": "task_not_found", "message": "任务不存在"})
    return task


def _safe_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise HTTPException(400, detail={"code": "path_traversal", "message": "非法路径"})
    return candidate


def _file_stream(path: Path):
    def iterator():
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk
    return iterator()


@router.get("/projects/{project_id}/tasks/{task_id}/files")
def list_task_files(project_id: str, task_id: str, path: str = Query(default=""), user=Depends(current_user)):
    project_access(project_id, "project:read", user)
    with session_scope() as db:
        _task_in_project(db, task_id, project_id)
    root = workspace_root() / task_id
    target = _safe_path(root, path) if path else root
    if not target.exists():
        return {"path": path, "entries": []}
    if not target.is_dir():
        raise HTTPException(400, detail={"code": "not_a_directory", "message": "路径不是目录"})
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append({
            "name": child.name,
            "path": (Path(path) / child.name).as_posix() if path else child.name,
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
            "is_dir": child.is_dir(),
        })
    return {"path": path, "entries": entries}


@router.get("/projects/{project_id}/tasks/{task_id}/files/download")
def download_task_file(project_id: str, task_id: str, path: str = Query(...), user=Depends(current_user)):
    project_access(project_id, "project:read", user)
    with session_scope() as db:
        _task_in_project(db, task_id, project_id)
    root = workspace_root() / task_id
    target = _safe_path(root, path)
    if not target.is_file():
        raise HTTPException(404, detail={"code": "file_not_found", "message": "文件不存在"})
    return StreamingResponse(
        _file_stream(target),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(target.name)}"},
    )
