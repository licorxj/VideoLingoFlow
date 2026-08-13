import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path) -> list[dict]:
    return [
        {"path": str(path.relative_to(root)), "size": path.stat().st_size, "sha256": _sha256(path)}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def create_backup(database: Path, workspace: Path, output: Path, redis_rdb: Path | None = None) -> Path:
    database = database.resolve()
    workspace = workspace.resolve()
    output = output.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / "backup"
        (root / "workspace").mkdir(parents=True)
        shutil.copy2(database, root / "control-plane.db")
        if workspace.is_dir():
            shutil.copytree(workspace, root / "workspace", dirs_exist_ok=True)
        if redis_rdb and redis_rdb.is_file():
            shutil.copy2(redis_rdb, root / "redis.rdb")
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database": str(database),
            "workspace": str(workspace),
            "files": _files(root),
        }
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(root, arcname="backup")
    return output


def restore_backup(archive_path: Path, database: Path, workspace: Path) -> dict:
    database = database.resolve()
    workspace = workspace.resolve()
    with tempfile.TemporaryDirectory() as temp:
        with tarfile.open(archive_path, "r:gz") as archive:
            temp_root = Path(temp).resolve()
            for member in archive.getmembers():
                target = (temp_root / member.name).resolve()
                if target != temp_root and temp_root not in target.parents:
                    raise ValueError(f"备份路径非法: {member.name}")
            archive.extractall(temp)
        root = Path(temp) / "backup"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        for item in manifest["files"]:
            path = root / item["path"]
            if not path.is_file() or path.stat().st_size != item["size"] or _sha256(path) != item["sha256"]:
                raise ValueError(f"备份校验失败: {item['path']}")
        database.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / "control-plane.db", database)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        if workspace.exists():
            shutil.rmtree(workspace)
        shutil.copytree(root / "workspace", workspace)
        return manifest
