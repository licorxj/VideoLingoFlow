# -*- coding: utf-8 -*-
"""Toonflow 存储路径约定：oss 素材库（源系统 data/oss 布局，物理落在本项目 data/ 下）。

布局：oss/{projectId}/{kind}/{uuid}.{ext}，kind ∈ images/videos/audios/thumbs。
对外（未来的静态服务）按源约定以 oss 相对路径存储，本模块负责与绝对路径互转。
"""
import shutil
import uuid
from pathlib import Path


def data_root() -> Path:
    from backend.control_plane.database import database_path

    return database_path().resolve().parent


def oss_root() -> Path:
    return data_root() / "toonflow" / "oss"


def project_dir(project_id: int | str, kind: str) -> Path:
    """项目素材目录并确保存在。kind: images / videos / audios / thumbs。"""
    d = oss_root() / str(project_id) / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_oss_file(project_id: int | str, kind: str, ext: str) -> Path:
    ext = (ext or ".bin").lstrip(".")
    return project_dir(project_id, kind) / f"{uuid.uuid4().hex}.{ext}"


def to_rel(path: str | Path) -> str:
    """绝对路径 → oss 相对路径（oss/...）；不在 oss 下时原样返回。"""
    try:
        return str(Path(path).resolve().relative_to(oss_root()))
    except (ValueError, OSError):
        return str(path)


def from_rel(rel: str) -> Path:
    """oss 相对路径（或绝对路径）→ 绝对路径。"""
    p = Path(rel)
    if p.is_absolute():
        return p
    return oss_root() / rel


def copy_into_oss(src: str | Path, project_id: int | str, kind: str) -> Path:
    """把已有文件复制进 oss，返回新文件绝对路径。"""
    src = Path(src)
    ext = src.suffix or ".bin"
    dest = new_oss_file(project_id, kind, ext)
    shutil.copy2(src, dest)
    return dest
