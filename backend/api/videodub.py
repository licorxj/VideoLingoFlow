"""视频配音工作台:工程持久化(视频/音频文件 + 工作区状态 JSON)与 vlf 任务导入。

媒体键约定:
    ws:videodub/{workspace_id}/...  本模块存储(视频源、上传音频),仅允许访问本工程目录
    vf:voices/previews/...          voiceforge 存储(TTS 配音片段直接引用预览音频)
vlf 任务媒体不走媒体键:直接用现成的 /api/files/stream?path=<任务内相对路径>&task_id=...
"""

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.api.control_plane_workspace import workspace_root
from backend.control_plane.database import session_scope
from backend.control_plane.models import VideoDubWorkspace
from backend.voiceforge.database import storage_root
from backend.voiceforge.storage import resolve_storage_key, safe_file_name

router = APIRouter()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".flv", ".ts", ".wmv"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".opus"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".m4v": "video/x-m4v",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
}


class StateUpdate(BaseModel):
    state: dict
    name: str | None = None
    duration: float | None = None


def _workspace_dir(workspace_id: str) -> Path:
    return storage_root() / "videodub" / workspace_id


def _summary(workspace: VideoDubWorkspace) -> dict:
    state = workspace.state or {}
    return {
        "id": workspace.id,
        "name": workspace.name,
        "video_name": workspace.video_name,
        "duration": workspace.duration,
        "subtitle_count": len(state.get("pairs", []) or []),
        "version": workspace.version,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


def _resolve_media_key(workspace_id: str, key: str) -> Path:
    if key.startswith("ws:"):
        rel = key[3:]
        if not rel.startswith(f"videodub/{workspace_id}/") or ".." in rel.split("/"):
            raise HTTPException(400, "非法媒体路径")
        root = storage_root().resolve()
        candidate = (root / rel).resolve()
        if root not in candidate.parents:
            raise HTTPException(400, "非法媒体路径")
        return candidate
    if key.startswith("vf:"):
        return resolve_storage_key(key[3:])
    raise HTTPException(400, "非法媒体键")


def _stream_copy(upload: UploadFile, destination: Path, allowed: set[str]) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed:
        allowed_text = " / ".join(sorted(allowed))
        raise HTTPException(400, f"仅支持以下格式:{allowed_text}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := upload.file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "文件过大")
                output.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception:
        destination.unlink(missing_ok=True)
        raise HTTPException(500, "文件保存失败") from None
    return suffix


def _require(workspace_id: str) -> VideoDubWorkspace:
    with session_scope() as session:
        workspace = session.get(VideoDubWorkspace, workspace_id)
        if workspace is None:
            raise HTTPException(404, "工程不存在")
        session.expunge(workspace)
        return workspace


@router.post("")
def create_workspace(file: UploadFile | None = File(None), name: str = Form("")):
    workspace_id = uuid.uuid4().hex
    video_name = safe_file_name(file.filename or "video.mp4") if file else ""
    title = name.strip() or (Path(video_name).stem or "视频配音工程")
    video_key = ""
    if file is not None:
        suffix = _stream_copy(file, _workspace_dir(workspace_id) / "source" / f"video{Path(video_name).suffix.lower()}", VIDEO_EXTENSIONS)
        video_key = f"videodub/{workspace_id}/source/video{suffix}"
    with session_scope() as session:
        workspace = VideoDubWorkspace(
            id=workspace_id,
            name=title,
            video_name=video_name,
            video_storage_key=video_key,
            duration=0.0,
            state={},
        )
        session.add(workspace)
        session.flush()
        return _summary(workspace)


@router.get("")
def list_workspaces():
    with session_scope() as session:
        rows = session.query(VideoDubWorkspace).order_by(VideoDubWorkspace.updated_at.desc()).all()
        for row in rows:
            session.expunge(row)
        return {"workspaces": [_summary(row) for row in rows]}


# --------------------------------------------------------------- vlf 任务导入


class VlfImportRequest(BaseModel):
    task_id: str
    dub_table: str
    video_path: str | None = None


class ReferenceFromTaskRequest(BaseModel):
    task_id: str
    path: str


def _vlf_task_dir(task_id: str) -> Path:
    root = workspace_root().resolve()
    candidate = (root / task_id).resolve()
    if root not in candidate.parents or not candidate.is_dir():
        raise HTTPException(404, "任务工作区不存在")
    return candidate


def _resolve_task_rel(task_dir: Path, rel: str) -> Path | None:
    """把任务内相对路径解析为绝对路径；越界或非法返回 None。"""
    rel = (rel or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    candidate = (task_dir / rel).resolve()
    if task_dir not in candidate.parents:
        return None
    return candidate


@router.get("/vlf-files")
def list_vlf_task_files(task_id: str):
    """列出任务工作区内可导入的配音任务表(dub_task_*.json)与视频文件。

    视频建议顺序:文件名含 adjusted_ > 含 input_ > 生成时间最新。
    """
    task_dir = _vlf_task_dir(task_id)
    cache_dir = task_dir / "cache"
    dub_tables = []
    if cache_dir.is_dir():
        for path in cache_dir.glob("dub_task_*.json"):
            if path.is_file():
                stat = path.stat()
                dub_tables.append({"path": path.relative_to(task_dir).as_posix(), "name": path.name, "size": stat.st_size, "mtime": int(stat.st_mtime)})
    dub_tables.sort(key=lambda item: -item["mtime"])

    videos = []
    for path in task_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        stat = path.stat()
        videos.append({"path": path.relative_to(task_dir).as_posix(), "name": path.name, "size": stat.st_size, "mtime": int(stat.st_mtime)})

    def rank(item: dict):
        name = item["name"].lower()
        if "adjusted_" in name:
            return (0, -item["mtime"])
        if "input_" in name:
            return (1, -item["mtime"])
        return (2, -item["mtime"])

    videos.sort(key=rank)
    return {"dubTables": dub_tables, "videos": videos}


@router.post("/vlf-import")
def import_vlf_task(data: VlfImportRequest):
    """解析选中的 dub_task_*.json,生成字幕/配音片段/原文片段的导入载荷。

    单句配音片段优先级 audio_file_adjusted -> audio_file -> 空;
    原文片段按 cache/refe/{index:04d}.wav 与句子 index 对齐,缺失为空。
    """
    task_dir = _vlf_task_dir(data.task_id)
    dub_path = _resolve_task_rel(task_dir, data.dub_table)
    if dub_path is None or dub_path.parent.name != "cache" or not dub_path.name.startswith("dub_task_") or dub_path.suffix != ".json":
        raise HTTPException(400, "请选择 cache 目录下的 dub_task_*.json 文件")
    if not dub_path.is_file():
        raise HTTPException(404, "配音任务表不存在")
    try:
        table = json.loads(dub_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"配音任务表解析失败:{exc}") from None
    segments = table.get("segments") or []
    if not segments:
        raise HTTPException(400, "配音任务表内没有句子")

    video_rel = ""
    video_name = ""
    if data.video_path:
        video = _resolve_task_rel(task_dir, data.video_path)
        if video is None or video.suffix.lower() not in VIDEO_EXTENSIONS or not video.is_file():
            raise HTTPException(400, "所选视频文件不存在")
        video_rel = data.video_path
        video_name = video.name

    pairs, dub_clips, original_clips = [], [], []
    missing_dub = 0
    missing_ref = 0
    for segment in segments:
        index = int(segment.get("index", len(pairs)))
        start = float(segment.get("start") or 0.0)
        end = max(float(segment.get("end") or start), start + 0.1)
        text = str(segment.get("text") or "")
        translation = str(segment.get("read_text") or "")

        # 配音片段:adjusted -> raw -> 空
        chosen = ""
        chosen_duration = 0.0
        source = ""
        for rel_key, duration_keys in (("audio_file_adjusted", ("adjusted_duration", "actual_audio_duration")), ("audio_file", ("real_duration", "duration"))):
            rel = str(segment.get(rel_key) or "").strip()
            if not rel:
                continue
            candidate = _resolve_task_rel(task_dir, rel)
            if candidate is None or not candidate.is_file():
                continue
            chosen = rel
            for key in duration_keys:
                chosen_duration = float(segment.get(key) or 0.0)
                if chosen_duration > 0:
                    break
            source = "adjusted" if rel_key == "audio_file_adjusted" else "raw"
            break
        if chosen:
            dub_clips.append({
                "index": index,
                "path": chosen,
                "name": text or Path(chosen).stem,
                "start": start,
                "duration": max(0.2, chosen_duration or (end - start)),
                "source": source,
            })
        else:
            missing_dub += 1

        # 原文片段:cache/refe/{index:04d}.wav
        ref_rel = f"cache/refe/{index:04d}.wav"
        ref_candidate = _resolve_task_rel(task_dir, ref_rel)
        if ref_candidate is not None and ref_candidate.is_file():
            ref_duration = float(segment.get("original_duration") or 0.0) or (end - start)
            original_clips.append({"index": index, "path": ref_rel, "name": f"{index:04d}.wav", "start": start, "duration": max(0.2, ref_duration)})
        else:
            missing_ref += 1

        dialect = str(segment.get("dialect") or segment.get("方言") or "")
        pairs.append({
            "index": index,
            "start": start,
            "end": end,
            "text": text,
            "translation": translation,
            "characterId": segment.get("character_id"),
            "readCharacterId": segment.get("read_character_id"),
            "toneDesc": str(segment.get("read_tone_desc") or ""),
            "dialect": dialect,
        })

    return {
        "video": {"path": video_rel, "name": video_name} if video_rel else None,
        "pairs": pairs,
        "dubClips": dub_clips,
        "originalClips": original_clips,
        "stats": {"segments": len(pairs), "missingDub": missing_dub, "missingRef": missing_ref},
    }


@router.post("/reference-from-task")
def reference_audio_from_task(data: ReferenceFromTaskRequest):
    """把 vlf 任务里的音频文件复制进 voiceforge 存储，供克隆模式作参考音频使用。"""
    task_dir = _vlf_task_dir(data.task_id)
    candidate = _resolve_task_rel(task_dir, data.path)
    if candidate is None or not candidate.is_file():
        raise HTTPException(404, "任务内音频文件不存在")
    dest_key = f"voices/references/vlf_{uuid.uuid4().hex}{candidate.suffix.lower()}"
    dest = resolve_storage_key(dest_key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, dest)
    return {"storage_key": dest_key}


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str):
    workspace = _require(workspace_id)
    return {
        "id": workspace.id,
        "name": workspace.name,
        "video_name": workspace.video_name,
        "video_key": f"ws:{workspace.video_storage_key}" if workspace.video_storage_key else "",
        "duration": workspace.duration,
        "state": workspace.state or {},
        "version": workspace.version,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


@router.put("/{workspace_id}/state")
def save_workspace_state(workspace_id: str, data: StateUpdate):
    with session_scope() as session:
        workspace = session.get(VideoDubWorkspace, workspace_id)
        if workspace is None:
            raise HTTPException(404, "工程不存在")
        workspace.state = data.state
        if data.name and data.name.strip():
            workspace.name = data.name.strip()
        if data.duration is not None and data.duration > 0:
            workspace.duration = data.duration
        session.flush()
        return {"id": workspace.id, "version": workspace.version, "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None}


@router.post("/{workspace_id}/audio")
def upload_workspace_audio(workspace_id: str, file: UploadFile = File(...)):
    _require(workspace_id)
    key_rel = f"videodub/{workspace_id}/audio/{uuid.uuid4().hex}{Path(safe_file_name(file.filename or 'audio.mp3')).suffix.lower()}"
    _stream_copy(file, storage_root() / key_rel, AUDIO_EXTENSIONS)
    return {"media_key": f"ws:{key_rel}"}


@router.get("/{workspace_id}/media")
def stream_workspace_media(workspace_id: str, key: str):
    path = _resolve_media_key(workspace_id, key)
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "媒体文件不存在")
    media_type = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: str):
    _require(workspace_id)
    with session_scope() as session:
        workspace = session.get(VideoDubWorkspace, workspace_id)
        if workspace is None:
            raise HTTPException(404, "工程不存在")
        session.delete(workspace)
    target = _workspace_dir(workspace_id)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    return {"deleted": workspace_id}
