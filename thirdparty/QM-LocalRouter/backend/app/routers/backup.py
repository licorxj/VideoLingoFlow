import os
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/backup", tags=["backup"])

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
CONFIG_PATH = DATA_DIR / "backup_config.json"
DEFAULT_BACKUP_DIR = DATA_DIR / "backups"


class BackupConfig(BaseModel):
    backup_dir: str = ""
    auto_backup_enabled: bool = False
    auto_backup_interval_hours: int = 24
    max_backups: int = 30


def _get_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        # Merge with defaults
        default = BackupConfig().model_dump()
        default.update(data)
        return default
    return BackupConfig().model_dump()


def _save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _get_backup_dir() -> Path:
    config = _get_config()
    custom = config.get("backup_dir", "")
    if custom and os.path.isdir(custom):
        return Path(custom)
    DEFAULT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_BACKUP_DIR


@router.get("/config")
async def get_backup_config():
    return _get_config()


@router.put("/config")
async def update_backup_config(data: BackupConfig):
    config = data.model_dump()
    _save_config(config)
    # Ensure backup directory exists
    _get_backup_dir()
    return config


@router.post("/create")
async def create_backup():
    """Create a backup of the database."""
    if not DB_PATH.exists():
        raise HTTPException(404, "Database file not found")

    backup_dir = _get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.db"
    dest = backup_dir / filename

    shutil.copy2(str(DB_PATH), str(dest))

    # Clean old backups
    config = _get_config()
    max_backups = config.get("max_backups", 30)
    backups = sorted(backup_dir.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max_backups:]:
        old.unlink(missing_ok=True)

    size_mb = dest.stat().st_size / (1024 * 1024)
    return {
        "filename": filename,
        "path": str(dest),
        "size_mb": round(size_mb, 2),
        "created_at": datetime.now().isoformat(),
    }


@router.get("/list")
async def list_backups():
    """List all available backups."""
    backup_dir = _get_backup_dir()
    if not backup_dir.exists():
        return []

    backups = []
    for f in sorted(backup_dir.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        backups.append({
            "filename": f.name,
            "path": str(f),
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return backups


@router.post("/restore")
async def restore_backup(file: UploadFile = File(...)):
    """Restore database from an uploaded backup file."""
    if not file.filename.endswith(".db"):
        raise HTTPException(400, "Only .db files are accepted")

    # Create a safety backup first
    if DB_PATH.exists():
        safety_dir = _get_backup_dir() / "pre_restore"
        safety_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(str(DB_PATH), str(safety_dir / f"pre_restore_{ts}.db"))

    # Write uploaded file
    content = await file.read()
    with open(DB_PATH, "wb") as f:
        f.write(content)

    return {"success": True, "message": "Database restored. Please restart the server."}


@router.post("/restore-local")
async def restore_local_backup(filename: str):
    """Restore from a local backup file by filename."""
    backup_dir = _get_backup_dir()
    backup_path = backup_dir / filename
    if not backup_path.exists():
        raise HTTPException(404, "Backup file not found")

    # Safety backup
    if DB_PATH.exists():
        safety_dir = _get_backup_dir() / "pre_restore"
        safety_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(str(DB_PATH), str(safety_dir / f"pre_restore_{ts}.db"))

    shutil.copy2(str(backup_path), str(DB_PATH))
    return {"success": True, "message": "Database restored. Please restart the server."}


@router.get("/download/{filename}")
async def download_backup(filename: str):
    """Download a backup file."""
    backup_dir = _get_backup_dir()
    filepath = backup_dir / filename
    if not filepath.exists():
        raise HTTPException(404, "Backup file not found")
    return FileResponse(str(filepath), filename=filename, media_type="application/octet-stream")


@router.delete("/{filename}")
async def delete_backup(filename: str):
    """Delete a backup file."""
    backup_dir = _get_backup_dir()
    filepath = backup_dir / filename
    if not filepath.exists():
        raise HTTPException(404, "Backup file not found")
    filepath.unlink()
    return {"success": True}


# Auto-backup background task
_last_auto_backup = 0


async def check_auto_backup():
    """Check if auto-backup is due. Call this on app startup or periodically."""
    global _last_auto_backup
    config = _get_config()
    if not config.get("auto_backup_enabled", False):
        return

    interval = config.get("auto_backup_interval_hours", 24) * 3600
    now = time.time()
    if now - _last_auto_backup < interval:
        return

    if not DB_PATH.exists():
        return

    backup_dir = _get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"auto_backup_{timestamp}.db"
    dest = backup_dir / filename
    shutil.copy2(str(DB_PATH), str(dest))

    # Clean old backups
    max_backups = config.get("max_backups", 30)
    backups = sorted(backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max_backups:]:
        old.unlink(missing_ok=True)

    _last_auto_backup = now
