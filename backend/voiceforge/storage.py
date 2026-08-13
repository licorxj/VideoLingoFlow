import hashlib
import mimetypes
import os
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException

from backend.voiceforge.database import load_config, storage_root


ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}


def safe_file_name(name: str, fallback: str = "audio.wav"):
    value = Path(name or fallback).name.strip()
    return value or fallback


def resolve_storage_key(storage_key: str) -> Path:
    root = storage_root().resolve()
    candidate = (root / storage_key).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(400, "非法文件路径")
    return candidate


def ensure_project_dirs(project_id: str):
    base = storage_root() / "projects" / project_id
    for name in ("source", "audio", "exports"):
        (base / name).mkdir(parents=True, exist_ok=True)
    return base


def copy_upload(upload, category: str, original_name: str):
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(400, "仅支持音频文件")
    max_bytes = int(load_config().get("max_upload_bytes", 524288000))
    key = f"{category}/{uuid.uuid4().hex}{suffix}"
    destination = resolve_storage_key(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                output.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(413, "文件超过大小限制")
            output.write(chunk)
    return key, total, mimetypes.guess_type(destination.name)[0]


def copy_legacy_file(source: Path, storage_key: str):
    destination = resolve_storage_key(storage_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
