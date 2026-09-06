"""素材库 HTTP 接口。

覆盖控制面库中的公共素材:图片(cp_images)、视频(cp_videos)、公共角色(cp_characters),
提供分页浏览、分组/标签/关键词筛选、上传登记、元数据更新与删除。
音频类素材(音效/背景音乐/环境音)由 voiceforge 库管理,前端直接复用 /api/voiceforge/assets;
文件预览统一走 /api/files/stream?path=<绝对路径>。
"""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select

from backend.control_plane.database import session_scope
from backend.control_plane.models import Character, ImageAsset, VideoAsset
from backend.creation import audio_refs, libraries, paths
from backend.creation.common import NotFoundError, ValidationError

router = APIRouter()

UPLOAD_ROOT = paths.DATA_ROOT / "materials"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


class CharacterCreate(BaseModel):
    name: str
    tags: list[str] = []
    gender: str = ""
    age: str = ""
    personality: str = ""
    occupation: str = ""
    aliases: list[str] = []
    voice_design: str = ""
    voice_ref: str = ""
    images_dir: str = ""


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    tags: Optional[list[str]] = None
    gender: Optional[str] = None
    age: Optional[str] = None
    personality: Optional[str] = None
    occupation: Optional[str] = None
    aliases: Optional[list[str]] = None
    voice_design: Optional[str] = None
    voice_ref: Optional[str] = None
    images_dir: Optional[str] = None


class ImageUpdate(BaseModel):
    group_tags: Optional[list[str]] = None
    custom_tags: Optional[list[str]] = None
    description: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    aspect_ratio: Optional[str] = None


class VideoUpdate(BaseModel):
    group_tags: Optional[list[str]] = None
    custom_tags: Optional[list[str]] = None
    description: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_seconds: Optional[float] = None


def _split_tags(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _with_abs_path(items: list[dict]) -> list[dict]:
    """给图片/视频记录补充 abs_path,供前端拼 /api/files/stream 预览地址。"""
    for item in items:
        try:
            item["abs_path"] = str(paths.resolve_public_path(item["path"]))
        except ValueError:
            item["abs_path"] = item["path"]
    return items


def _paged(items: list[dict], page: int, page_size: int) -> dict:
    safe_size = max(1, min(page_size, 100))
    safe_page = max(1, page)
    start = (safe_page - 1) * safe_size
    return {"items": items[start : start + safe_size], "total": len(items), "page": safe_page, "page_size": safe_size}


def _call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _save_upload(file: UploadFile, subdir: str, allowed: set[str]) -> Path:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix or '(缺少后缀)'}")
    target_dir = UPLOAD_ROOT / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过 512MB 大小限制")
                out.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="文件保存失败")
    if size == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="空文件")
    return target


def _remove_owned_file(rel_path: str) -> None:
    """仅删除 data/materials/ 内本系统上传的文件,用户手工登记的外部路径不动。"""
    if rel_path.startswith("data/materials/"):
        try:
            paths.resolve_public_path(rel_path).unlink(missing_ok=True)
        except ValueError:
            pass


# ---------------------------------------------------------------- 总览


@router.get("/summary")
def summary():
    with session_scope() as session:
        images = session.scalar(select(func.count()).select_from(ImageAsset)) or 0
        videos = session.scalar(select(func.count()).select_from(VideoAsset)) or 0
        characters = session.scalar(select(func.count()).select_from(Character)) or 0
    try:
        audio = len(audio_refs.list_audio_assets())
    except Exception:
        audio = 0
    return {"images": images, "videos": videos, "characters": characters, "audio": audio}


# ---------------------------------------------------------------- 图片


@router.get("/images")
def list_images(page: int = 1, page_size: int = 12, group: str = "", tag: str = "", search: str = ""):
    items = libraries.list_images(group_tag=group, keyword=search)
    if tag:
        items = [item for item in items if tag in item["group_tags"] or tag in item["custom_tags"]]
    all_rows = libraries.list_images()
    payload = _paged(_with_abs_path(items), page, page_size)
    payload["groups"] = sorted({value for item in all_rows for value in item["group_tags"]})
    payload["tags"] = sorted({value for item in all_rows for value in [*item["group_tags"], *item["custom_tags"]]})
    return payload


@router.post("/images")
async def upload_image(
    file: UploadFile = File(...),
    group_tags: str = Form(""),
    custom_tags: str = Form(""),
    description: str = Form(""),
):
    target = _save_upload(file, "images", IMAGE_EXTS)
    try:
        row = _call(libraries.add_image, paths.normalize_public_path(target), group_tags=_split_tags(group_tags), custom_tags=_split_tags(custom_tags), description=description)
        return _with_abs_path([row])[0]
    except HTTPException:
        target.unlink(missing_ok=True)
        raise


@router.put("/images/{image_id}")
def update_image(image_id: str, data: ImageUpdate):
    return _call(libraries.update_image, image_id, **data.model_dump(exclude_none=True))


@router.get("/images/{image_id}")
def get_image_by_id(image_id: str):
    row = _call(libraries.get_image, image_id)
    return _with_abs_path([row])[0]


@router.delete("/images/{image_id}")
def delete_image(image_id: str):
    row = _call(libraries.get_image, image_id)
    _call(libraries.delete_image, image_id)
    _remove_owned_file(row["path"])
    return {"ok": True}


# ---------------------------------------------------------------- 视频


@router.get("/videos")
def list_videos(page: int = 1, page_size: int = 12, group: str = "", tag: str = "", search: str = ""):
    items = libraries.list_videos(group_tag=group, keyword=search)
    if tag:
        items = [item for item in items if tag in item["group_tags"] or tag in item["custom_tags"]]
    all_rows = libraries.list_videos()
    payload = _paged(_with_abs_path(items), page, page_size)
    payload["groups"] = sorted({value for item in all_rows for value in item["group_tags"]})
    payload["tags"] = sorted({value for item in all_rows for value in [*item["group_tags"], *item["custom_tags"]]})
    return payload


@router.post("/videos")
async def upload_video(
    file: UploadFile = File(...),
    group_tags: str = Form(""),
    custom_tags: str = Form(""),
    description: str = Form(""),
):
    target = _save_upload(file, "videos", VIDEO_EXTS)
    try:
        row = _call(libraries.add_video, paths.normalize_public_path(target), group_tags=_split_tags(group_tags), custom_tags=_split_tags(custom_tags), description=description)
        return _with_abs_path([row])[0]
    except HTTPException:
        target.unlink(missing_ok=True)
        raise


@router.put("/videos/{video_id}")
def update_video(video_id: str, data: VideoUpdate):
    return _call(libraries.update_video, video_id, **data.model_dump(exclude_none=True))


@router.get("/videos/{video_id}")
def get_video_by_id(video_id: str):
    row = _call(libraries.get_video, video_id)
    return _with_abs_path([row])[0]


@router.delete("/videos/{video_id}")
def delete_video(video_id: str):
    row = _call(libraries.get_video, video_id)
    _call(libraries.delete_video, video_id)
    _remove_owned_file(row["path"])
    return {"ok": True}


# ---------------------------------------------------------------- 公共角色


@router.get("/characters")
def list_characters(page: int = 1, page_size: int = 12, tag: str = "", search: str = ""):
    items = libraries.list_characters(tag=tag, keyword=search)
    for item in items:
        item["images_dir_abs"] = _with_abs_path([{"path": item["images_dir"]}])[0]["abs_path"] if item["images_dir"] else ""
    payload = _paged(items, page, page_size)
    payload["tags"] = sorted({value for item in libraries.list_characters() for value in item["tags"]})
    return payload


@router.post("/characters")
def create_character(data: CharacterCreate):
    return _call(libraries.create_character, data.name, tags=data.tags, gender=data.gender, age=data.age, personality=data.personality, occupation=data.occupation, aliases=data.aliases, voice_design=data.voice_design, voice_ref=data.voice_ref, images_dir=data.images_dir)


@router.put("/characters/{character_id}")
def update_character(character_id: str, data: CharacterUpdate):
    return _call(libraries.update_character, character_id, **data.model_dump(exclude_none=True))


@router.get("/characters/{character_id}")
def get_character_by_id(character_id: str):
    row = _call(libraries.get_character, character_id)
    if row["images_dir"]:
        try:
            row["images_dir_abs"] = str(paths.resolve_public_path(row["images_dir"]))
        except ValueError:
            row["images_dir_abs"] = ""
    return row


@router.get("/voices/{voice_id}")
def get_voice_record(voice_id: str):
    """音色素材详情(供节点卡片预览与执行回查),数据来自 voiceforge 音色库。"""
    try:
        return audio_refs.resolve_audio_ref(audio_refs.make_voice_ref(voice_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/characters/{character_id}")
def delete_character(character_id: str):
    _call(libraries.delete_character, character_id)
    return {"ok": True}
