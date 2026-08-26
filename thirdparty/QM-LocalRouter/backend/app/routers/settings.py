import json
import socket
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
SETTINGS_PATH = DATA_DIR / "app_settings.json"
REPOSITORY_ROOT = BASE_DIR.parent
FRONTEND_DIR = REPOSITORY_ROOT / "frontend"

DEFAULTS = {
    "output_protocol": "openai",
    "default_model": "",
    "default_provider_id": 0,
    "lan_access": False,
}

class AppSettings(BaseModel):
    output_protocol: str = "openai"
    default_model: str = ""
    default_provider_id: int = 0
    lan_access: bool = False

def _get_settings() -> dict:
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        default = DEFAULTS.copy()
        default.update(data)
        return default
    return DEFAULTS.copy()

def _save_settings(data: dict):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_output_protocol() -> str:
    return _get_settings().get("output_protocol", "openai")

def get_lan_ip() -> str:
    """Detect the LAN IP address of this machine."""
    try:
        # Try to connect to a known external address to determine the active interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    # Fallback: try hostname resolution
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


async def _run_command(*args: str, cwd: Path, timeout: int = 120) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except FileNotFoundError as exc:
        raise HTTPException(503, "Git or npm is not available on this server") from exc
    except TimeoutError as exc:
        raise HTTPException(504, f"Command timed out: {args[0]}") from exc

    return process.returncode, stdout.decode("utf-8", errors="replace").strip(), stderr.decode("utf-8", errors="replace").strip()


async def _repository_status(fetch: bool) -> dict:
    if not (REPOSITORY_ROOT / ".git").is_dir():
        raise HTTPException(404, "This installation is not a Git repository")

    code, branch, error = await _run_command("git", "branch", "--show-current", cwd=REPOSITORY_ROOT)
    if code != 0 or not branch:
        raise HTTPException(500, error or "Unable to determine the current branch")

    remote_ref = "FETCH_HEAD"
    if fetch:
        code, _, error = await _run_command("git", "fetch", "origin", branch, cwd=REPOSITORY_ROOT)
        if code != 0:
            raise HTTPException(502, error or "Unable to fetch remote repository")

    code, remote_url, error = await _run_command("git", "remote", "get-url", "origin", cwd=REPOSITORY_ROOT)
    if code != 0:
        raise HTTPException(500, error or "Unable to determine the repository remote")

    code, local_commit, error = await _run_command("git", "rev-parse", "HEAD", cwd=REPOSITORY_ROOT)
    if code != 0:
        raise HTTPException(500, error or "Unable to determine the local revision")

    code, behind, error = await _run_command("git", "rev-list", "--count", f"HEAD..{remote_ref}", cwd=REPOSITORY_ROOT)
    if code != 0:
        raise HTTPException(500, error or "Unable to compare repository revisions")

    code, status, error = await _run_command("git", "status", "--porcelain", cwd=REPOSITORY_ROOT)
    if code != 0:
        raise HTTPException(500, error or "Unable to inspect the working tree")

    return {
        "repository_url": remote_url,
        "branch": branch,
        "local_commit": local_commit,
        "behind_count": int(behind or 0),
        "update_available": int(behind or 0) > 0,
        "working_tree_clean": not bool(status),
    }

@router.get("")
async def get_settings():
    return _get_settings()

@router.put("")
async def update_settings(data: AppSettings):
    current = _get_settings()
    current.update(data.model_dump(exclude_unset=True))
    _save_settings(current)
    return current

@router.get("/lan-ip")
async def lan_ip():
    return {"ip": get_lan_ip()}


@router.get("/repository")
async def get_repository_status():
    return await _repository_status(fetch=True)


@router.post("/repository/update")
async def update_repository():
    status = await _repository_status(fetch=True)
    if not status["working_tree_clean"]:
        raise HTTPException(409, "The working tree contains local changes. Commit or stash them before updating.")
    if not status["update_available"]:
        return {**status, "updated": False, "build_output": "Already up to date."}

    code, output, error = await _run_command("git", "pull", "--ff-only", "origin", status["branch"], cwd=REPOSITORY_ROOT)
    if code != 0:
        raise HTTPException(502, error or output or "Unable to update the repository")

    code, build_output, error = await _run_command("npm", "run", "build", cwd=FRONTEND_DIR, timeout=300)
    if code != 0:
        raise HTTPException(500, error or build_output or "Frontend build failed after the repository update")

    updated_status = await _repository_status(fetch=False)
    return {**updated_status, "updated": True, "build_output": build_output}
