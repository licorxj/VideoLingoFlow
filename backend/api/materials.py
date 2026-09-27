"""素材库 HTTP 接口。

覆盖控制面库中的公共素材:图片(cp_images)、视频(cp_videos)、公共角色(cp_characters),
提供分页浏览、分组/标签/关键词筛选、上传登记、元数据更新与删除。
音频类素材(音效/背景音乐/环境音)由 voiceforge 库管理,前端直接复用 /api/voiceforge/assets;
文件预览统一走 /api/files/stream?path=<绝对路径>。

另提供素材库落盘目录的文件管理接口(/files*):浏览 data/materials、data/libraries、
data/characters 内的真实文件,支持搜索/筛选/排序/分页与上传、重命名、新建目录、删除。
"""

import shutil
import uuid
from datetime import datetime
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

# 素材库落盘根目录:key → (data/ 相对路径, 展示名)
FILE_ROOTS: dict[str, tuple[str, str]] = {
    "materials": ("data/materials", "上传素材"),
    "libraries": ("data/libraries", "入库素材"),
    "characters": ("data/characters", "角色图集"),
}


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
    return {"images": images, "videos": videos, "characters": characters, "audio": audio, "files": _count_files()}


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


# ---------------------------------------------------------------- 素材库文件管理


class FileRenameRequest(BaseModel):
    root: str
    path: str
    new_name: str


class FileMkdirRequest(BaseModel):
    root: str
    dir: str = ""
    name: str


KIND_EXTS: dict[str, set[str]] = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico", ".avif", ".tif", ".tiff"},
    "video": {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus", ".wma", ".aiff", ".aif"},
    "text": {".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".srt", ".ass", ".ssa", ".vtt", ".yaml", ".yml", ".xml", ".log", ".ini", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".bat", ".sh"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
}
KIND_LABELS = {"image": "图片", "video": "视频", "audio": "音频", "text": "文本", "archive": "压缩包", "other": "其它"}


def _kind_of(suffix: str) -> str:
    for kind, exts in KIND_EXTS.items():
        if suffix in exts:
            return kind
    return "other"


def _root_dir(root_key: str) -> Path:
    if root_key not in FILE_ROOTS:
        raise HTTPException(status_code=400, detail=f"未知素材根目录: {root_key}")
    return paths.resolve_public_path(FILE_ROOTS[root_key][0])


def _member_path(root_key: str, rel: str) -> Path:
    """把根目录内的相对路径解析成绝对路径,越界(含 ..)直接拒绝。"""
    root = _root_dir(root_key).resolve()
    cleaned = (rel or "").replace("\\", "/").strip().strip("/")
    if ".." in cleaned.split("/"):
        raise HTTPException(status_code=400, detail="路径不合法")
    target = root if not cleaned else (root / cleaned).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="路径越界")
    return target


def _data_rel(path: Path) -> str:
    """绝对路径 → data/ 相对路径;不在项目 data 内返回空串。"""
    try:
        return path.resolve().relative_to(paths.PROJECT_ROOT).as_posix()
    except ValueError:
        return ""


def _registered_map() -> dict[str, tuple[str, str]]:
    """已登记的图片/视频素材:data/ 相对路径 → (类别, 记录 id)。"""
    mapping: dict[str, tuple[str, str]] = {}
    with session_scope() as session:
        for row in session.scalars(select(ImageAsset)).all():
            mapping[row.path] = ("image", row.id)
        for row in session.scalars(select(VideoAsset)).all():
            mapping[row.path] = ("video", row.id)
    return mapping


def _character_dirs() -> set[str]:
    """公共角色多视角图目录(data/ 相对路径)。"""
    with session_scope() as session:
        return {row.images_dir for row in session.scalars(select(Character)).all() if row.images_dir}


def _file_item(root_key: str, path: Path, registered: dict[str, tuple[str, str]], char_dirs: set[str]) -> Optional[dict]:
    try:
        stat = path.stat()
    except OSError:
        return None
    root = _root_dir(root_key).resolve()
    try:
        rel_root = path.resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    parent = Path(rel_root).parent.as_posix()
    if parent == ".":
        parent = ""
    suffix = path.suffix.lower()
    kind = _kind_of(suffix)
    data_rel = _data_rel(path)
    registered_as = registered.get(data_rel, ("", ""))[0]
    if not registered_as:
        for char_dir in char_dirs:
            if data_rel and (data_rel == char_dir or data_rel.startswith(f"{char_dir}/")):
                registered_as = "character"
                break
    return {
        "root": root_key,
        "root_label": FILE_ROOTS[root_key][1],
        "name": path.name,
        "dir": parent,
        "rel_path": rel_root,
        "path": data_rel,
        "abs_path": str(path),
        "ext": suffix.lstrip("."),
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind, "其它"),
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "registered": bool(registered_as),
        "registered_as": registered_as,
        "streamable": kind in {"image", "video", "audio"},
        "text_preview": kind == "text",
    }


def _walk_root(root_key: str, subdir: str = "") -> list[dict]:
    base = _member_path(root_key, subdir)
    if not base.is_dir():
        return []
    registered = _registered_map()
    char_dirs = _character_dirs()
    items = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        item = _file_item(root_key, path, registered, char_dirs)
        if item:
            items.append(item)
    return items


def _count_files() -> int:
    total = 0
    for root_key in FILE_ROOTS:
        try:
            total += len(_walk_root(root_key))
        except Exception:
            continue
    return total


def _safe_filename(name: str) -> str:
    cleaned = Path((name or "").replace("\\", "/")).name.replace("\x00", "").strip()
    if not cleaned or cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail="名称不能为空")
    return cleaned


def _unique_target(directory: Path, name: str) -> Path:
    """同名文件自动加 _1/_2 后缀,不覆盖已有文件。"""
    target = directory / name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for index in range(1, 1000):
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=409, detail="同名文件过多,请先重命名")


def _remove_records_for(paths_rel: set[str]) -> list[str]:
    """删除文件后,把指向它们的图片/视频素材登记一并软删除,保持素材库一致。"""
    if not paths_rel:
        return []
    removed: list[str] = []
    registered = _registered_map()
    for rel in sorted(paths_rel):
        entry = registered.get(rel)
        if not entry:
            continue
        kind, record_id = entry
        try:
            if kind == "image":
                libraries.delete_image(record_id)
            else:
                libraries.delete_video(record_id)
        except NotFoundError:
            continue
        removed.append(f"{kind}:{record_id}")
    return removed


@router.get("/files")
def list_material_files(
    root: str = "all",
    dir: str = "",
    search: str = "",
    kind: str = "",
    sort: str = "mtime",
    order: str = "desc",
    page: int = 1,
    page_size: int = 24,
):
    """浏览素材库落盘目录内的文件(默认聚合全部根目录,递归)。"""
    if root not in ("", "all") and root not in FILE_ROOTS:
        raise HTTPException(status_code=400, detail=f"未知素材根目录: {root}")
    aggregate = root in ("", "all")
    keys = list(FILE_ROOTS) if aggregate else [root]

    all_items: list[dict] = []
    for key in keys:
        all_items.extend(_walk_root(key, "" if aggregate else dir))

    dirs = [] if aggregate else sorted({item["dir"] for item in all_items if item["dir"]})
    keyword = (search or "").strip().lower()
    kind_filter = "" if kind in ("", "all") else kind
    items = [
        item
        for item in all_items
        if (not keyword or keyword in item["name"].lower() or keyword in item["rel_path"].lower())
        and (not kind_filter or item["kind"] == kind_filter)
    ]

    sorters = {
        "name": lambda item: item["name"].lower(),
        "path": lambda item: item["rel_path"].lower(),
        "size": lambda item: item["size"],
        "mtime": lambda item: item["mtime"],
        "kind": lambda item: (item["kind"], item["name"].lower()),
    }
    items.sort(key=sorters.get(sort, sorters["mtime"]), reverse=order != "asc")

    kind_counts: dict[str, int] = {}
    for item in items:
        kind_counts[item["kind"]] = kind_counts.get(item["kind"], 0) + 1

    payload = _paged(items, page, page_size)
    payload.update(
        {
            "root": root or "all",
            "dir": dir,
            "dirs": dirs,
            "kind_counts": kind_counts,
            "total_size": sum(item["size"] for item in items),
            "roots": [
                {"key": key, "label": FILE_ROOTS[key][1], "rel": FILE_ROOTS[key][0], "exists": _root_dir(key).is_dir()}
                for key in FILE_ROOTS
            ],
        }
    )
    return payload


@router.post("/files/upload")
async def upload_material_file(file: UploadFile = File(...), root: str = Form("materials"), dir: str = Form("")):
    """把文件写入素材库目录(不登记元数据,仅落盘)。"""
    target_dir = _member_path(root, dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_target(target_dir, _safe_filename(file.filename or ""))
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
    return {"ok": True, "item": _file_item(root, target, _registered_map(), _character_dirs())}


@router.post("/files/mkdir")
def create_material_dir(data: FileMkdirRequest):
    parent = _member_path(data.root, data.dir)
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / _safe_filename(data.name)
    if target.exists():
        raise HTTPException(status_code=409, detail=f"目录或文件已存在: {target.name}")
    target.mkdir()
    return {"ok": True, "path": _data_rel(target)}


@router.post("/files/rename")
def rename_material_file(data: FileRenameRequest):
    source = _member_path(data.root, data.path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {data.path}")
    if source.resolve() == _root_dir(data.root).resolve():
        raise HTTPException(status_code=400, detail="不能重命名素材库根目录")
    target = source.parent / _safe_filename(data.new_name)
    if target.resolve() == source.resolve():
        return {"ok": True, "path": _data_rel(source)}
    if target.exists():
        raise HTTPException(status_code=409, detail=f"同名文件已存在: {target.name}")
    source.rename(target)
    updated: list[str] = []
    if not target.is_dir():
        before, after = _data_rel(source), _data_rel(target)
        registered = _registered_map()
        entry = registered.get(before)
        if entry and after:
            kind, record_id = entry
            try:
                if kind == "image":
                    libraries.update_image(record_id, path=after)
                else:
                    libraries.update_video(record_id, path=after)
                updated.append(f"{kind}:{record_id}")
            except (NotFoundError, ValidationError):
                pass
    return {"ok": True, "path": _data_rel(target), "updated_records": updated}


@router.delete("/files")
def delete_material_file(root: str, path: str):
    """删除文件或目录;目录递归删除,并同步软删除指向被删文件的素材登记。"""
    target = _member_path(root, path)
    if target.resolve() == _root_dir(root).resolve():
        raise HTTPException(status_code=400, detail="不能删除素材库根目录")
    if target.is_dir():
        rels = {_data_rel(item) for item in target.rglob("*") if item.is_file() and _data_rel(item)}
        shutil.rmtree(target)
    elif target.is_file():
        rels = {_data_rel(target)} - {""}
        target.unlink()
    else:
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    return {"ok": True, "removed_records": _remove_records_for(rels)}
