"""文件中转站：文件类型判定、入库登记与取件查询。

设计约定：

- **只登记元信息，不移动/不复制文件**：``path`` 保持文件的原始位置，可以是绝对路径，
  也可以是任务工作区内的相对路径（配合 ``task_id`` 还原，供 /api/files/stream 预览）；
- 同一路径重复入库视为刷新：更新名称/类型/所属任务，**保留首次入库时间**（幂等，
  任务重跑不会把已有条目刷到队首）；
- 取件排序支持：最新入库 / 最旧入库 / 排序序号（第 N 个）/ 文件名称。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import func, or_, select

from backend.control_plane.database import session_scope
from backend.control_plane.models import FileTransit

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".amr"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tiff"}
TEXT_EXTS = {".txt", ".md", ".srt", ".ass", ".ssa", ".vtt", ".json", ".csv", ".xml", ".yaml", ".yml"}

FILE_TYPE_LABELS = {
    "video": "视频",
    "audio": "音频",
    "image": "图片",
    "text": "文本",
    "other": "其它",
}

ORDER_LATEST = "latest"
ORDER_OLDEST = "oldest"
ORDER_INDEX = "index"
ORDER_NAME = "name"

ORDER_LABELS = {
    ORDER_LATEST: "最新入库",
    ORDER_OLDEST: "最旧入库",
    ORDER_INDEX: "排序序号",
    ORDER_NAME: "文件名称",
}


def classify_file_type(name_or_path: str) -> str:
    """按扩展名判定文件类型；未知扩展名归为 other。"""
    ext = os.path.splitext(str(name_or_path or ""))[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in TEXT_EXTS:
        return "text"
    return "other"


def row_to_dict(row: FileTransit) -> Dict[str, Any]:
    created = getattr(row, "created_at", None)
    return {
        "id": row.id,
        "name": row.name,
        "file_type": row.file_type,
        "file_type_label": FILE_TYPE_LABELS.get(row.file_type, row.file_type),
        "task_name": row.task_name,
        "path": row.path,
        "task_id": row.task_id or "",
        "seq": int(getattr(row, "seq", 0) or 0),
        "created_at": created.isoformat() if created else "",
    }


def _normalize(raw: Any) -> List[str]:
    """把节点输入归一化为文件路径列表。

    必须**递归展开**：节点同时接入「单文件 + 文件列表」两个端口时，合并后的输入是
    ``[str, [str, str]]`` 这种嵌套结构，只做一层遍历会把内层列表 str() 成一条假路径。
    支持形态：路径字符串 / ``{path|file|file_path}`` 对象 / 嵌套列表 / JSON 数组字符串。
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        paths: List[str] = []
        for item in raw:
            for p in _normalize(item):
                if p not in paths:
                    paths.append(p)
        return paths
    if isinstance(raw, dict):
        for key in ("path", "file", "file_path", "filepath"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return [value.strip()]
        for key in ("paths", "items", "files", "list"):
            value = raw.get(key)
            if isinstance(value, (list, tuple)):
                return _normalize(list(value))
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                import json

                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return _normalize(parsed)
            except Exception:
                pass
        return [text]
    text = str(raw or "").strip()
    return [text] if text else []


def ingest_paths(raw: Any, task_id: str = "", task_name: str = "") -> List[Dict[str, Any]]:
    """把一批文件路径登记进中转站，返回落库后的条目（按入库先后）。"""
    paths = _normalize(raw)
    if not paths:
        return []
    result: List[Dict[str, Any]] = []
    with session_scope() as session:
        next_seq = int(session.scalar(select(func.coalesce(func.max(FileTransit.seq), 0))) or 0) + 1
        for path in paths:
            name = os.path.basename(path.rstrip("/\\")) or path
            file_type = classify_file_type(name)
            row = session.scalar(select(FileTransit).where(FileTransit.path == path))
            if row is None:
                row = FileTransit(
                    name=name,
                    file_type=file_type,
                    task_name=task_name or "",
                    path=path,
                    task_id=task_id or "",
                    seq=next_seq,
                )
                next_seq += 1
                session.add(row)
                session.flush()
            else:
                # 重复入库：刷新归属与显示信息，保留首次入库时间
                row.name = name
                row.file_type = file_type
                if task_name:
                    row.task_name = task_name
                if task_id:
                    row.task_id = task_id
                session.flush()
            result.append(row_to_dict(row))
    return result


def _ordered_stmt(file_type: str, keyword: str, order: str):
    stmt = select(FileTransit)
    if file_type and file_type != "all":
        stmt = stmt.where(FileTransit.file_type == file_type)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(FileTransit.name.like(like), FileTransit.task_name.like(like)))
    if order == ORDER_NAME:
        stmt = stmt.order_by(FileTransit.name.asc(), FileTransit.seq.desc())
    elif order == ORDER_OLDEST or order == ORDER_INDEX:
        stmt = stmt.order_by(FileTransit.seq.asc())
    else:
        stmt = stmt.order_by(FileTransit.seq.desc())
    return stmt


def list_files(
    file_type: str = "",
    keyword: str = "",
    order: str = ORDER_LATEST,
    limit: int = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """查询中转站条目，返回 {"items": [...], "total": n}。"""
    with session_scope() as session:
        base = _ordered_stmt(file_type, keyword, order)
        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = session.scalars(base.offset(max(0, offset)).limit(max(1, min(int(limit), 500)))).all()
        return {"items": [row_to_dict(row) for row in rows], "total": int(total)}


def pick_file(
    file_type: str = "",
    keyword: str = "",
    order: str = ORDER_LATEST,
    index: int = 1,
    path: str = "",
) -> Optional[Dict[str, Any]]:
    """按规则取一件素材：指定 path 时直接命中，否则按类型+排序取。"""
    with session_scope() as session:
        if path:
            row = session.scalar(select(FileTransit).where(FileTransit.path == path))
            return row_to_dict(row) if row is not None else None
        stmt = _ordered_stmt(file_type, keyword, order)
        if order == ORDER_INDEX:
            pos = max(1, int(index or 1)) - 1
            rows = session.scalars(stmt.offset(pos).limit(1)).all()
        else:
            rows = session.scalars(stmt.limit(1)).all()
        row = rows[0] if rows else None
        return row_to_dict(row) if row is not None else None


def remove_file(item_id: str) -> bool:
    """软删除一条中转站记录（不删磁盘文件）。"""
    with session_scope() as session:
        row = session.get(FileTransit, item_id)
        if row is None:
            return False
        session.delete(row)
        session.flush()
        return True


def file_exists(path: str) -> bool:
    """登记的文件是否仍然存在（相对路径按 task_id 还原后再判断）。"""
    if not path:
        return False
    if os.path.isabs(path):
        return os.path.isfile(path)
    return True  # 相对路径交由调用方按任务工作区解析
