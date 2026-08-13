import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from backend.control_plane.assets import AssetAccessError, AssetDescriptor, AssetIntegrityError, AssetStore, LocalAssetStore, MinioAssetStore, asset_object_key, asset_record
from backend.control_plane.checkpoints import record_checkpoint, reusable_checkpoint
from backend.control_plane.compat import legacy_asset_path, legacy_asset_sha256
from backend.control_plane.database import session_scope
from backend.control_plane.models import Asset, Checkpoint, Task, TaskNode
from backend.control_plane.security import audit, current_user, project_access, require_permission

router = APIRouter()


class CheckpointRequest(BaseModel):
    checkpoint_key: str = Field(min_length=1, max_length=256)
    input_hash: str = Field(min_length=1, max_length=64, pattern="^[A-Fa-f0-9]+$")
    step_version: str = Field(min_length=1, max_length=128)
    node_config: dict = Field(default_factory=dict)
    asset_id: str = Field(min_length=1, max_length=32)


class CheckpointReuseRequest(BaseModel):
    checkpoint_key: str = Field(min_length=1, max_length=256)
    input_hash: str = Field(min_length=1, max_length=64, pattern="^[A-Fa-f0-9]+$")
    step_version: str = Field(min_length=1, max_length=128)
    node_config: dict = Field(default_factory=dict)


def _asset_view(item: Asset) -> dict:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "task_id": item.task_id,
        "kind": item.kind,
        "object_key": item.object_key,
        "content_sha256": item.content_sha256,
        "size_bytes": item.size_bytes,
        "content_type": item.content_type,
        "metadata": item.metadata_json,
        "expires_at": item.expires_at,
    }


def _legacy_path(item: Asset) -> Path | None:
    tasks_root = Path(os.getenv("TASKS_ROOT", Path(__file__).resolve().parents[2] / "tasks"))
    return legacy_asset_path(tasks_root, item.task_id or "", item.object_key)


def _store() -> AssetStore:
    if os.getenv("CONTROL_PLANE_ASSET_STORE", "local").lower() == "minio":
        return MinioAssetStore()
    return LocalAssetStore()


def _task_in_project(db, task_id: str, project_id: str) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.project_id == project_id))
    if not task:
        raise HTTPException(404, detail={"code": "task_not_found", "message": "任务不存在"})
    return task


@router.get("/projects/{project_id}/assets")
def list_assets(project_id: str, kind: str | None = None, user=Depends(current_user)):
    project_access(project_id, "project:read", user)
    with session_scope() as db:
        statement = select(Asset).where(Asset.project_id == project_id).order_by(desc(Asset.created_at))
        if kind:
            statement = statement.where(Asset.kind == kind)
        return {"assets": [_asset_view(item) for item in db.scalars(statement).all()]}


@router.post("/projects/{project_id}/assets", status_code=201)
def upload_asset(
    project_id: str,
    kind: str = Query(...),
    name: str = Query(..., min_length=1, max_length=512),
    task_id: str | None = Query(default=None),
    expires_at: datetime | None = Query(default=None),
    file: UploadFile = File(...),
    x_content_sha256: str = Header(..., min_length=64, max_length=64),
    x_content_length: int = Header(..., ge=0),
    user=Depends(current_user),
):
    project_access(project_id, "project:write", user)
    try:
        object_key = asset_object_key(project_id, kind, name)
    except Exception as exc:
        raise HTTPException(400, detail={"code": "invalid_asset_key", "message": str(exc)}) from exc
    descriptor = AssetDescriptor(project_id, kind, object_key, x_content_sha256.lower(), x_content_length, file.content_type or "application/octet-stream")
    store = _store()
    uploaded = False
    try:
        with session_scope() as db:
            if task_id:
                _task_in_project(db, task_id, project_id)
            store.put(file.file, descriptor, {"original-name": name})
            uploaded = True
            item = asset_record(descriptor, task_id=task_id, expires_at=expires_at)
            item.metadata_json = {"original_name": name}
            db.add(item)
            db.flush()
            audit(db, user.id, "asset_uploaded", "asset", item.id, {"project_id": project_id, "kind": kind, "size_bytes": x_content_length})
            return {"asset": _asset_view(item)}
    except AssetIntegrityError as exc:
        raise HTTPException(400, detail={"code": "asset_integrity_failed", "message": str(exc)}) from exc
    except Exception:
        if uploaded:
            store.remove(descriptor)
        raise


@router.get("/assets/{asset_id}/download")
def download_asset(asset_id: str, user=Depends(current_user)):
    with session_scope() as db:
        item = db.get(Asset, asset_id)
        if not item:
            raise HTTPException(404, detail={"code": "asset_not_found", "message": "资产不存在"})
        project_id = item.project_id
        task_id = item.task_id
        object_key = item.object_key
        content_type = item.content_type
        file_name = item.metadata_json.get("original_name", Path(object_key).name)
        project_access(project_id, "asset:download", user)
        descriptor = AssetDescriptor(project_id, item.kind, object_key, item.content_sha256, item.size_bytes, content_type)
        db.expunge(item)
    store = _store()
    try:
        if not store.verify(descriptor):
            raise FileNotFoundError(object_key)
        stream = store.stream(descriptor)
    except Exception:
        path = _legacy_path(item)
        if not path:
            raise HTTPException(404, detail={"code": "asset_object_not_found", "message": "资产对象不存在"})
        if legacy_asset_sha256(path) != item.content_sha256:
            raise HTTPException(409, detail={"code": "asset_integrity_failed", "message": "旧资产校验和不一致"})
        stream = _file_stream(path)
    with session_scope() as db:
        audit(db, user.id, "asset_downloaded", "asset", asset_id, {"project_id": project_id})
    return StreamingResponse(stream, media_type=content_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_name)}"})


@router.post("/assets/{asset_id}/download-url")
def create_download_url(asset_id: str, expires_seconds: int = Query(default=300, ge=30, le=900), user=Depends(current_user)):
    with session_scope() as db:
        item = db.get(Asset, asset_id)
        if not item:
            raise HTTPException(404, detail={"code": "asset_not_found", "message": "资产不存在"})
        project_access(item.project_id, "asset:download", user)
        descriptor = AssetDescriptor(item.project_id, item.kind, item.object_key, item.content_sha256, item.size_bytes, item.content_type)
        try:
            url = _store().presigned_download(descriptor, expires_seconds)
        except AssetAccessError as exc:
            raise HTTPException(501, detail={"code": "presigned_download_unsupported", "message": str(exc)}) from exc
        audit(db, user.id, "asset_download_url_issued", "asset", asset_id, {"expires_seconds": expires_seconds})
        return {"url": url, "expires_seconds": expires_seconds}


def _file_stream(path: Path):
    def iterator():
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk
    return iterator()


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, user=Depends(current_user)):
    store = _store()
    with session_scope() as db:
        item = db.get(Asset, asset_id)
        if not item:
            raise HTTPException(404, detail={"code": "asset_not_found", "message": "资产不存在"})
        project_access(item.project_id, "project:write", user)
        protected = bool(item.task_id and db.scalar(select(Task.id).where(Task.id == item.task_id, Task.status.in_({"created", "queued", "running", "cancelling"})))) or bool(db.scalar(select(Checkpoint.id).where(Checkpoint.output_object_key == item.object_key)))
        if protected:
            raise HTTPException(409, detail={"code": "asset_in_use", "message": "资产仍被运行任务或检查点引用"})
        descriptor = AssetDescriptor(item.project_id, item.kind, item.object_key, item.content_sha256, item.size_bytes, item.content_type)
        db.delete(item)
        audit(db, user.id, "asset_deleted", "asset", asset_id, {"project_id": descriptor.project_id})
    try:
        store.remove(descriptor)
    except Exception:
        pass
    return {"ok": True}


@router.post("/assets/cleanup")
def cleanup_assets(user=Depends(require_permission("admin"))):
    store = _store()
    removed = 0
    with session_scope() as db:
        items = db.scalars(select(Asset).where(Asset.expires_at.is_not(None), Asset.expires_at <= datetime.now(timezone.utc))).all()
        for item in items:
            protected = bool(item.task_id and db.scalar(select(Task.id).where(Task.id == item.task_id, Task.status.in_({"created", "queued", "running", "cancelling"})))) or bool(db.scalar(select(Checkpoint.id).where(Checkpoint.output_object_key == item.object_key)))
            if protected:
                continue
            db.delete(item)
            audit(db, user.id, "asset_expired_cleanup", "asset", item.id)
            try:
                store.remove(AssetDescriptor(item.project_id, item.kind, item.object_key, item.content_sha256, item.size_bytes, item.content_type))
            except Exception:
                pass
            removed += 1
    return {"removed": removed}


@router.post("/projects/{project_id}/nodes/{node_id}/checkpoints")
def save_checkpoint(project_id: str, node_id: str, request: CheckpointRequest, user=Depends(current_user)):
    project_access(project_id, "project:write", user)
    store = _store()
    with session_scope() as db:
        node = db.scalar(select(TaskNode).join(Task).where(TaskNode.id == node_id, Task.project_id == project_id))
        if not node:
            raise HTTPException(404, detail={"code": "node_not_found", "message": "节点不存在"})
        asset = db.get(Asset, request.asset_id)
        if not asset or asset.project_id != project_id:
            raise HTTPException(404, detail={"code": "asset_not_found", "message": "检查点资产不存在"})
        descriptor = AssetDescriptor(project_id, asset.kind, asset.object_key, asset.content_sha256, asset.size_bytes, asset.content_type)
        item = record_checkpoint(db, node_id, request.checkpoint_key, request.input_hash, request.step_version, request.node_config, descriptor, store)
        audit(db, user.id, "checkpoint_saved", "checkpoint", item.id, {"project_id": project_id, "node_id": node_id})
        return {"checkpoint": {"id": item.id, "checkpoint_key": item.checkpoint_key, "output_object_key": item.output_object_key, "output_checksum": item.output_checksum, "version": item.version}}


@router.post("/projects/{project_id}/nodes/{node_id}/checkpoints/reuse")
def reuse_checkpoint(project_id: str, node_id: str, request: CheckpointReuseRequest, user=Depends(current_user)):
    project_access(project_id, "project:read", user)
    with session_scope() as db:
        node = db.scalar(select(TaskNode).join(Task).where(TaskNode.id == node_id, Task.project_id == project_id))
        if not node:
            raise HTTPException(404, detail={"code": "node_not_found", "message": "节点不存在"})
        item = reusable_checkpoint(db, node_id, request.checkpoint_key, request.input_hash, request.step_version, request.node_config, _store())
        if item:
            audit(db, user.id, "checkpoint_reused", "checkpoint", item.id, {"project_id": project_id})
        return {"hit": item is not None, "checkpoint": {"id": item.id, "output_object_key": item.output_object_key, "output_checksum": item.output_checksum} if item else None}
