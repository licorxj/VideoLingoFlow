"""公共素材库读写脚本:角色库(cp_characters)、图片素材库(cp_images)、视频素材库(cp_videos)。

图片/视频素材的 path 一律为 data/ 内的项目根相对路径(见 paths.py);
角色库的 voice_ref 为 vf:voices:<id> 音频引用(见 audio_refs.py)。
"""

from math import gcd
from pathlib import Path
import json

from sqlalchemy import select

from backend.control_plane.database import session_scope
from backend.control_plane.models import Character, ImageAsset, VideoAsset
from backend.creation import audio_refs, paths
from backend.creation.common import NotFoundError, ValidationError, ensure_tag_list, row_to_dict

_CHARACTER_FIELDS = {"name", "tags", "gender", "age", "personality", "occupation", "aliases", "voice_design", "voice_ref", "images_dir", "origin_creation_id"}
_IMAGE_FIELDS = {"path", "width", "height", "aspect_ratio", "group_tags", "custom_tags", "description"}
_VIDEO_FIELDS = {"path", "width", "height", "duration_seconds", "group_tags", "custom_tags", "description"}


# ---------------------------------------------------------------- 角色库


def create_character(
    name: str,
    *,
    tags=None,
    gender: str = "",
    age: str = "",
    personality: str = "",
    occupation: str = "",
    aliases=None,
    voice_design: str = "",
    voice_ref: str = "",
    images_dir: str = "",
    origin_creation_id: str | None = None,
) -> dict:
    """向公共角色库新增角色;voice_ref 必须是 vf:voices:<id> 引用,images_dir 必须是 data/ 相对路径。"""
    if not name or not str(name).strip():
        raise ValidationError("角色名称不能为空")
    if voice_ref and not audio_refs.is_audio_ref(voice_ref):
        raise ValidationError(f"voice_ref 必须是 vf: 格式的音频素材引用: {voice_ref}")
    with session_scope() as session:
        character = Character(
            name=str(name).strip(),
            tags=ensure_tag_list(tags),
            gender=gender,
            age=age,
            personality=personality,
            occupation=occupation,
            aliases=ensure_tag_list(aliases),
            voice_design=voice_design,
            voice_ref=voice_ref,
            images_dir=paths.normalize_public_path(images_dir) if images_dir else "",
            origin_creation_id=origin_creation_id,
        )
        session.add(character)
        session.flush()
        return row_to_dict(character)


def get_character(character_id: str) -> dict:
    with session_scope() as session:
        row = session.get(Character, character_id)
        if row is None:
            raise NotFoundError(f"角色不存在: {character_id}")
        return row_to_dict(row)


def list_characters(tag: str = "", keyword: str = "", origin_creation_id: str = "") -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(Character).order_by(Character.created_at)).all()
    result = []
    for row in rows:
        if tag and tag not in row.tags:
            continue
        if origin_creation_id and row.origin_creation_id != origin_creation_id:
            continue
        if keyword and keyword not in row.name and keyword not in row.personality and keyword not in row.occupation:
            continue
        result.append(row_to_dict(row))
    return result


def update_character(character_id: str, **fields) -> dict:
    unknown = set(fields) - _CHARACTER_FIELDS
    if unknown:
        raise ValidationError(f"不支持更新的字段: {sorted(unknown)}")
    if fields.get("voice_ref") and not audio_refs.is_audio_ref(fields["voice_ref"]):
        raise ValidationError(f"voice_ref 必须是 vf: 格式的音频素材引用: {fields['voice_ref']}")
    if fields.get("images_dir"):
        fields["images_dir"] = paths.normalize_public_path(fields["images_dir"])
    if "tags" in fields:
        fields["tags"] = ensure_tag_list(fields["tags"])
    if "aliases" in fields:
        fields["aliases"] = ensure_tag_list(fields["aliases"])
    with session_scope() as session:
        row = session.get(Character, character_id)
        if row is None:
            raise NotFoundError(f"角色不存在: {character_id}")
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return row_to_dict(row)


def delete_character(character_id: str) -> None:
    with session_scope() as session:
        row = session.get(Character, character_id)
        if row is None:
            raise NotFoundError(f"角色不存在: {character_id}")
        session.delete(row)


# ---------------------------------------------------------------- 图片素材库


def add_image(
    path: str,
    *,
    width: int | None = None,
    height: int | None = None,
    aspect_ratio: str = "",
    group_tags=None,
    custom_tags=None,
    description: str = "",
    verify: bool = True,
) -> dict:
    """登记公共图片素材;缺尺寸/比例时会尝试用 PIL 自动补齐。"""
    rel = paths.normalize_public_path(path)
    target = paths.resolve_public_path(rel)
    if verify and not target.is_file():
        raise FileNotFoundError(f"图片文件不存在: {target}")
    if width is None or height is None or not aspect_ratio:
        probed = _probe_image(target)
        width = width if width is not None else probed.get("width")
        height = height if height is not None else probed.get("height")
        aspect_ratio = aspect_ratio or probed.get("aspect_ratio", "")
    with session_scope() as session:
        if session.scalar(select(ImageAsset.id).where(ImageAsset.path == rel)):
            raise ValidationError(f"图片素材已登记过: {rel}")
        row = ImageAsset(path=rel, width=width, height=height, aspect_ratio=aspect_ratio, group_tags=ensure_tag_list(group_tags), custom_tags=ensure_tag_list(custom_tags), description=description)
        session.add(row)
        session.flush()
        return row_to_dict(row)


def get_image(image_id: str) -> dict:
    with session_scope() as session:
        row = session.get(ImageAsset, image_id)
        if row is None:
            raise NotFoundError(f"图片素材不存在: {image_id}")
        return row_to_dict(row)


def list_images(group_tag: str = "", custom_tag: str = "", keyword: str = "") -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(ImageAsset).order_by(ImageAsset.created_at)).all()
    result = []
    for row in rows:
        if group_tag and group_tag not in row.group_tags:
            continue
        if custom_tag and custom_tag not in row.custom_tags:
            continue
        if keyword and keyword not in row.path and keyword not in row.description:
            continue
        result.append(row_to_dict(row))
    return result


def update_image(image_id: str, **fields) -> dict:
    unknown = set(fields) - _IMAGE_FIELDS
    if unknown:
        raise ValidationError(f"不支持更新的字段: {sorted(unknown)}")
    if "path" in fields and fields["path"]:
        fields["path"] = paths.normalize_public_path(fields["path"])
    if "group_tags" in fields:
        fields["group_tags"] = ensure_tag_list(fields["group_tags"])
    if "custom_tags" in fields:
        fields["custom_tags"] = ensure_tag_list(fields["custom_tags"])
    with session_scope() as session:
        row = session.get(ImageAsset, image_id)
        if row is None:
            raise NotFoundError(f"图片素材不存在: {image_id}")
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return row_to_dict(row)


def delete_image(image_id: str) -> None:
    with session_scope() as session:
        row = session.get(ImageAsset, image_id)
        if row is None:
            raise NotFoundError(f"图片素材不存在: {image_id}")
        session.delete(row)


# ---------------------------------------------------------------- 视频素材库


def add_video(
    path: str,
    *,
    width: int | None = None,
    height: int | None = None,
    duration_seconds: float | None = None,
    group_tags=None,
    custom_tags=None,
    description: str = "",
    verify: bool = True,
) -> dict:
    """登记公共视频素材;缺尺寸/时长时会尝试用 ffprobe 自动补齐。"""
    rel = paths.normalize_public_path(path)
    target = paths.resolve_public_path(rel)
    if verify and not target.is_file():
        raise FileNotFoundError(f"视频文件不存在: {target}")
    if width is None or height is None or duration_seconds is None:
        probed = _probe_video(target)
        width = width if width is not None else probed.get("width")
        height = height if height is not None else probed.get("height")
        duration_seconds = duration_seconds if duration_seconds is not None else probed.get("duration_seconds")
    with session_scope() as session:
        if session.scalar(select(VideoAsset.id).where(VideoAsset.path == rel)):
            raise ValidationError(f"视频素材已登记过: {rel}")
        row = VideoAsset(path=rel, width=width, height=height, duration_seconds=duration_seconds, group_tags=ensure_tag_list(group_tags), custom_tags=ensure_tag_list(custom_tags), description=description)
        session.add(row)
        session.flush()
        return row_to_dict(row)


def get_video(video_id: str) -> dict:
    with session_scope() as session:
        row = session.get(VideoAsset, video_id)
        if row is None:
            raise NotFoundError(f"视频素材不存在: {video_id}")
        return row_to_dict(row)


def list_videos(group_tag: str = "", custom_tag: str = "", keyword: str = "") -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(VideoAsset).order_by(VideoAsset.created_at)).all()
    result = []
    for row in rows:
        if group_tag and group_tag not in row.group_tags:
            continue
        if custom_tag and custom_tag not in row.custom_tags:
            continue
        if keyword and keyword not in row.path and keyword not in row.description:
            continue
        result.append(row_to_dict(row))
    return result


def update_video(video_id: str, **fields) -> dict:
    unknown = set(fields) - _VIDEO_FIELDS
    if unknown:
        raise ValidationError(f"不支持更新的字段: {sorted(unknown)}")
    if "path" in fields and fields["path"]:
        fields["path"] = paths.normalize_public_path(fields["path"])
    if "group_tags" in fields:
        fields["group_tags"] = ensure_tag_list(fields["group_tags"])
    if "custom_tags" in fields:
        fields["custom_tags"] = ensure_tag_list(fields["custom_tags"])
    with session_scope() as session:
        row = session.get(VideoAsset, video_id)
        if row is None:
            raise NotFoundError(f"视频素材不存在: {video_id}")
        for key, value in fields.items():
            setattr(row, key, value)
        session.flush()
        return row_to_dict(row)


def delete_video(video_id: str) -> None:
    with session_scope() as session:
        row = session.get(VideoAsset, video_id)
        if row is None:
            raise NotFoundError(f"视频素材不存在: {video_id}")
        session.delete(row)


# ---------------------------------------------------------------- 探测辅助


def probe_image_file(path: str | Path) -> dict:
    """读取图片宽高与最简比例;PIL 不可用或解析失败返回空 dict。"""
    return _probe_image(Path(path))


def probe_video_file(path: str | Path) -> dict:
    """用 ffprobe 读取视频宽高与时长;ffprobe 不可用或解析失败返回空 dict。"""
    return _probe_video(Path(path))


def _probe_image(target: Path) -> dict:
    try:
        from PIL import Image
    except ImportError:
        return {}
    try:
        with Image.open(target) as image:
            width, height = image.size
    except Exception:
        return {}
    divisor = gcd(width, height) or 1
    return {"width": width, "height": height, "aspect_ratio": f"{width // divisor}:{height // divisor}"}


def _probe_video(target: Path) -> dict:
    """用 ffprobe 读取视频宽高与时长;ffprobe 不可用或解析失败时返回空。"""
    import shutil
    import subprocess

    exe = shutil.which("ffprobe")
    if exe is None or not target.is_file():
        return {}
    try:
        output = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-show_entries", "format=duration", "-of", "json", str(target)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        payload = json.loads(output.stdout or "{}")
    except Exception:
        return {}
    stream = (payload.get("streams") or [{}])[0]
    duration = payload.get("format", {}).get("duration")
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "duration_seconds": float(duration) if duration else None,
    }
