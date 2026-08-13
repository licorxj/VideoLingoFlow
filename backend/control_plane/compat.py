import hashlib
from pathlib import Path


def legacy_asset_path(tasks_root: Path, task_id: str, object_key: str) -> Path | None:
    if not task_id or not object_key or Path(object_key).is_absolute() or ".." in Path(object_key).parts:
        return None
    root = (tasks_root / task_id).resolve()
    candidate = (root / object_key).resolve()
    if candidate != root and root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def legacy_asset_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
