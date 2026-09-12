"""批次归档：把批次下各任务的产物按 task_name 归档到目标文件夹。

单个任务的归档流程：
1. 在归档目标文件夹下以「task.json 中的 task_name」新建文件夹；
2. 复制 workflow.json / task.json（必归档）以及用户勾选的其他文件，保持原始相对结构；
3. 复制成功后删除本地任务目录（删除失败则跳过，不阻断归档）；
4. 数据库中将任务标记为已归档（status=archived）并记录归档路径，供后续载回。
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from backend.control_plane.database import session_scope
from backend.control_plane.models import Task
from backend.control_plane.workflow_runtime import _workspace

ARCHIVED_STATUS = "archived"
REQUIRED_FILES = ("workflow.json", "task.json")
RUNNING_STATUSES = {"running", "stopping", "queued"}

VIDEO_EXTS = {"mp4", "avi", "mkv", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "ts", "m2ts"}
SUBTITLE_EXTS = {"srt", "ass", "ssa", "vtt", "sub", "lrc"}
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "svg", "avif"}
AUDIO_EXTS = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "aiff", "aif", "opus", "mka"}
# 音频片段可能非常多，只扫描产物主目录 cache / output，避免版面被海量片段淹没
AUDIO_SCAN_PREFIXES = ("cache/", "output/")

CATEGORY_LABELS = {
    "video": "视频文件",
    "subtitle": "字幕文件",
    "image": "图片文件",
    "audio": "音频文件",
    "other": "其他文件",
}

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def category_of(rel_path: str) -> str:
    """按扩展名把产物归入 视频/字幕/图片/音频/其他 五类。

    音频仅在 cache / output 目录下的片段才归入「音频文件」，其余位置（如根目录散落
    的音频）归入「其他」，避免在归档面板里出现过多与任务产物无关的条目。
    """
    ext = os.path.splitext(rel_path)[1].lower().lstrip(".")
    if ext in VIDEO_EXTS:
        return "video"
    if ext in SUBTITLE_EXTS:
        return "subtitle"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS and rel_path.lower().startswith(AUDIO_SCAN_PREFIXES):
        return "audio"
    return "other"


def _legacy_root() -> Path:
    """旧版任务目录（backend/tasks/{task_id}），兼容历史任务。"""
    return Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "tasks"


def resolve_task_dir(task_id: str) -> Path | None:
    """返回任务实际存在的工作区目录（优先控制平面工作区，回退旧 tasks 目录）。"""
    for candidate in (_workspace(task_id), _legacy_root() / task_id):
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def _iter_task_files(root: Path) -> list[dict]:
    """递归列出任务目录下的全部文件（相对路径 posix 形式）。"""
    files: list[dict] = []
    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            size = path.stat().st_size
        except OSError:
            continue
        files.append({
            "path": rel,
            "name": path.name,
            "size": size,
            "category": category_of(rel),
            "required": rel in REQUIRED_FILES,
        })
    files.sort(key=lambda item: item["path"])
    return files


def task_archive_name(task_id: str) -> str:
    """归档目录名：优先 task.json 中的 task_name，其次 payload.batch.task_name，最后任务 ID。"""
    task_dir = resolve_task_dir(task_id)
    if task_dir is not None:
        task_json = task_dir / "task.json"
        if task_json.is_file():
            try:
                data = json.loads(task_json.read_text(encoding="utf-8"))
                name = data.get("task_name") if isinstance(data, dict) else None
                if isinstance(name, str) and name.strip():
                    return name.strip()
            except (OSError, json.JSONDecodeError, ValueError):
                pass
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is not None:
            meta = (task.payload or {}).get("batch") or {}
            name = meta.get("task_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return task_id


def _safe_folder_name(name: str, fallback: str) -> str:
    cleaned = _INVALID_NAME_CHARS.sub("_", name).strip().strip(".")
    return cleaned or fallback


def describe_batch_tasks(tasks: list[Task]) -> list[dict]:
    """列出批次下各任务的归档产物清单，供归档弹窗展示。"""
    result: list[dict] = []
    for task in tasks:
        task_dir = resolve_task_dir(task.id)
        result.append({
            "task_id": task.id,
            "task_name": task_archive_name(task.id),
            "status": task.status,
            "dir": str(task_dir) if task_dir else "",
            "exists": task_dir is not None,
            "files": _iter_task_files(task_dir) if task_dir is not None else [],
        })
    return result


def _mark_archived(task_id: str, dest: Path) -> None:
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            return
        previous_status = task.status
        task.status = ARCHIVED_STATUS
        task.archive_path = str(dest)
        task.archived_at = now
        task.deletion_requested = False
        task.payload = {
            **(task.payload or {}),
            "archive": {"path": str(dest), "at": now.isoformat(), "previous_status": previous_status},
        }


def _mark_restored(task_id: str, status: str) -> None:
    """载回成功后清除归档标记，并把状态恢复为归档前的状态。"""
    with session_scope() as session:
        task = session.get(Task, task_id)
        if task is None:
            return
        task.status = status or "succeeded"
        task.archive_path = None
        task.archived_at = None
        payload = dict(task.payload or {})
        payload.pop("archive", None)
        task.payload = payload


def list_archived_tasks() -> list[dict]:
    """列出全部已归档任务（供「历史项目 → 加载已归档项目」弹窗展示）。"""
    result: list[dict] = []
    with session_scope() as session:
        tasks = (
            session.query(Task)
            .filter(Task.status == ARCHIVED_STATUS)
            .order_by(Task.archived_at.desc())
            .all()
        )
        for task in tasks:
            payload = task.payload or {}
            batch = payload.get("batch") or {}
            workflow = payload.get("workflow") or {}
            archive = payload.get("archive") or {}
            archive_path = getattr(task, "archive_path", None) or archive.get("path") or ""
            result.append({
                "task_id": task.id,
                "task_name": batch.get("task_name") or payload.get("task_name") or task.id,
                "workflow_name": batch.get("workflow_name") or workflow.get("name") or "",
                "archive_path": archive_path,
                "archived_at": task.archived_at.isoformat() if task.archived_at else None,
                "exists": bool(archive_path) and Path(archive_path).is_dir(),
            })
    return result


def restore_archived_tasks(task_ids: list[str]) -> dict:
    """把已归档项目载回本地工作区。

    单个任务流程：以 task_id 新建工作区目录 → 从归档文件夹按原始结构复制全部文件 →
    删除归档文件夹（删除失败不阻断）→ 清除库中归档标记并恢复归档前状态。
    """
    restored: list[dict] = []
    failed: list[dict] = []

    for task_id in dict.fromkeys(task_ids or []):
        try:
            with session_scope() as session:
                task = session.get(Task, task_id)
                if task is None:
                    raise RuntimeError("任务不存在")
                if task.status != ARCHIVED_STATUS:
                    raise RuntimeError("任务未处于已归档状态")
                payload = task.payload or {}
                archive = payload.get("archive") or {}
                archive_path = getattr(task, "archive_path", None) or archive.get("path")
                previous_status = archive.get("previous_status") or "succeeded"

            if not archive_path:
                raise RuntimeError("缺少归档路径记录")
            archive_dir = Path(archive_path)
            if not archive_dir.is_dir():
                raise RuntimeError("归档文件夹不存在")

            dest = _workspace(task_id)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(archive_dir, dest, dirs_exist_ok=True)
            # 复制成功后再删除归档文件夹；删除失败（占用/权限）则跳过，不影响载回结果
            shutil.rmtree(archive_dir, ignore_errors=True)

            _mark_restored(task_id, previous_status)
            restored.append({
                "task_id": task_id,
                "dir": str(dest),
                "archive_path": str(archive_dir),
            })
        except Exception as exc:  # noqa: BLE001 - 单个任务失败不阻断整批载回
            failed.append({"task_id": task_id, "error": str(exc)})

    return {"restored": restored, "failed": failed}


def _archive_one(
    task_id: str,
    task_dir: Path,
    target_root: Path,
    selected_paths: list[str] | None,
    used_names: dict[str, int],
) -> tuple[Path, str]:
    raw_name = task_archive_name(task_id)
    folder = _safe_folder_name(raw_name, task_id[:8])
    key = folder.lower()
    if key in used_names:
        used_names[key] += 1
        folder = f"{folder}_{used_names[key]}"
    used_names[folder.lower()] = 1
    dest = target_root / folder

    available = {item["path"] for item in _iter_task_files(task_dir)}
    if selected_paths is None:
        wanted = sorted(available)
    else:
        wanted = [rel for rel in dict.fromkeys(selected_paths) if rel in available]
    # workflow.json / task.json 始终归档
    for required in REQUIRED_FILES:
        if required in available and required not in wanted:
            wanted.append(required)
    if not wanted:
        raise RuntimeError("没有可归档的文件")

    for rel in wanted:
        source = task_dir / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    # 复制成功后再删除本地任务目录；删除失败（占用/权限）则跳过，不影响归档结果
    shutil.rmtree(task_dir, ignore_errors=True)

    _mark_archived(task_id, dest)
    return dest, raw_name


def archive_batch_tasks(
    tasks: list[Task],
    target_dir: str,
    selections: dict[str, list[str]] | None = None,
) -> dict:
    """执行批次归档。

    selections: {task_id: [相对文件路径...]}；缺失该任务时表示归档其全部文件。
    """
    if not target_dir or not str(target_dir).strip():
        raise ValueError("归档目标文件夹不能为空")
    target_root = Path(str(target_dir)).expanduser()
    try:
        target_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"无法创建归档目标文件夹：{exc}") from exc

    selections = selections or {}
    archived: list[dict] = []
    blocked: list[dict] = []
    failed: list[dict] = []
    used_names: dict[str, int] = {}

    for task in tasks:
        if task.status == ARCHIVED_STATUS:
            blocked.append({"task_id": task.id, "reason": "任务已归档"})
            continue
        if task.status in RUNNING_STATUSES:
            blocked.append({"task_id": task.id, "reason": "任务正在执行，无法归档"})
            continue
        task_dir = resolve_task_dir(task.id)
        if task_dir is None:
            failed.append({"task_id": task.id, "error": "任务目录不存在"})
            continue
        try:
            dest, name = _archive_one(task.id, task_dir, target_root, selections.get(task.id), used_names)
        except Exception as exc:  # noqa: BLE001 - 单个任务失败不阻断批次归档
            failed.append({"task_id": task.id, "error": str(exc)})
            continue
        archived.append({"task_id": task.id, "task_name": name, "path": str(dest)})

    return {
        "target_dir": str(target_root),
        "archived": archived,
        "blocked": blocked,
        "failed": failed,
    }
