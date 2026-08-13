import subprocess
import sys
import os
from fastapi import APIRouter
from app.config import settings

router = APIRouter(prefix="/api/service", tags=["service"])

_backend_process = None

@router.post("/start")
async def start_service():
    global _backend_process
    try:
        if _backend_process and _backend_process.poll() is None:
            return {"status": "already_running", "pid": _backend_process.pid}
        
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _backend_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "0.0.0.0", "--port", str(settings.BACKEND_PORT), "--reload"],
            cwd=backend_dir,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return {"status": "started", "pid": _backend_process.pid}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/stop")
async def stop_service():
    global _backend_process
    try:
        if _backend_process and _backend_process.poll() is None:
            _backend_process.terminate()
            _backend_process = None
            return {"status": "stopped"}
        return {"status": "not_running"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
