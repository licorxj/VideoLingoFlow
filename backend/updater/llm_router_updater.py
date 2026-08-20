import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

_lock = threading.Lock()
_status = {
    "status": "idle",
    "message": "",
    "log": [],
    "updated_at": 0,
    "task_id": "",
}


def _set_status(status: str, message: str) -> None:
    with _lock:
        _status["status"] = status
        _status["message"] = message
        _status["updated_at"] = time.time()
        _status["log"] = (_status["log"] + [f"[{time.strftime('%H:%M:%S')}] {message}"])[-100:]


def get_status() -> dict:
    with _lock:
        return {**_status, "log": list(_status["log"])}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_update() -> None:
    root = _project_root()
    script = root / "scripts" / "llmrouter" / "mgr.py"
    if not script.is_file():
        _set_status("error", "未找到路由器更新脚本")
        return
    try:
        _set_status("updating", "正在更新 QM-LocalRouter 代码和依赖...")
        result = subprocess.run(
            [sys.executable, str(script), "update"],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            shell=False,
        )
        output = (result.stdout or "").strip()
        if output:
            with _lock:
                _status["log"] = (_status["log"] + output.splitlines()[-100:])[-100:]
        if result.returncode:
            _set_status("error", f"更新失败，退出码 {result.returncode}")
            return
        _set_status("success", "更新完成，请重启路由器服务使新代码生效")
    except subprocess.TimeoutExpired:
        _set_status("error", "更新超时，已停止等待")
    except OSError as exc:
        _set_status("error", f"无法启动更新脚本：{exc}")


def run_update() -> dict:
    with _lock:
        if _status["status"] == "updating":
            return {"ok": False, "message": "更新正在进行中"}
        _status.update({
            "status": "updating",
            "message": "更新任务已启动",
            "log": [],
            "updated_at": time.time(),
            "task_id": uuid.uuid4().hex[:12],
        })
    threading.Thread(target=_run_update, daemon=True, name="llm-router-update").start()
    return {"ok": True, "message": "更新任务已启动"}
