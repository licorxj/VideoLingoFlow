
"""
File browser API for selecting local files.
"""
import asyncio
import os
import re
import subprocess
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/files", tags=["files"])

class BrowseRequest(BaseModel):
    path: str = ""

class FileItem(BaseModel):
    name: str
    path: str
    isDir: bool
    size: Optional[int] = None

def _safe_path(p: str) -> str:
    """Resolve and ensure path is safe."""
    resolved = os.path.realpath(os.path.expanduser(p))
    return resolved


def _control_plane_workspace_path(path: str) -> Path | None:
    requested = Path(path)
    parts = requested.parts
    try:
        tasks_index = [part.lower() for part in parts].index("tasks")
    except ValueError:
        return None
    relative = parts[tasks_index + 1:]
    if len(relative) < 2 or not relative[0].startswith("flow_"):
        return None
    legacy_task_id = relative[0]
    if any(part in {"", ".", ".."} for part in relative):
        return None
    workspace_root = Path(os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", Path.cwd() / "control_plane_workspaces")).resolve()
    workspaces = [workspace_root / legacy_task_id]
    if legacy_task_id.startswith("flow_"):
        workflow_id = legacy_task_id[len("flow_"):]
        try:
            from backend.control_plane.database import session_scope
            from backend.control_plane.models import Task
            with session_scope() as session:
                for task in session.query(Task).order_by(Task.created_at.desc()):
                    if ((task.payload or {}).get("workflow") or {}).get("id") == workflow_id:
                        workspaces.insert(0, workspace_root / task.id)
                        break
        except Exception:
            pass
    for workspace in workspaces:
        workspace = workspace.resolve()
        candidate = (workspace.joinpath(*relative[1:])).resolve()
        if workspace in candidate.parents and candidate.is_file():
            return candidate
    return None


def _stream_path(path: str, task_id: str | None = None) -> str:
    safe = _safe_path(path)
    if os.path.isfile(safe):
        return safe
    workspace_path = _control_plane_workspace_path(path)
    if workspace_path:
        return str(workspace_path)
    # 新布局：相对路径（如 output/xxx、cache/xxx）相对任务工作区 {task_id} 解析，
    # 让预览器/文件读取忠实显示任务内连入的产物。
    if task_id:
        workspace_root = Path(os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", Path.cwd() / "control_plane_workspaces")).resolve()
        candidate = (workspace_root / task_id / path).resolve()
        if workspace_root in candidate.parents and candidate.is_file():
            return str(candidate)
    return safe

@router.post("/browse")
async def browse_directory(req: BrowseRequest):
    """List files in a directory."""
    target = _safe_path(req.path) if req.path else _get_home()
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Directory not found")
    if not os.path.isdir(target):
        # Return file info
        name = os.path.basename(target)
        return {"path": os.path.dirname(target), "items": [
            {"name": name, "path": target, "isDir": False, "size": os.path.getsize(target)}
        ]}

    items = []
    try:
        for entry in sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                item = {
                    "name": entry.name,
                    "path": entry.path,
                    "isDir": entry.is_dir(),
                }
                if not entry.is_dir():
                    try:
                        item["size"] = entry.stat().st_size
                    except Exception:
                        pass
                items.append(item)
            except PermissionError:
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    parent = os.path.dirname(target) if target != _get_home() else None
    return {"path": target, "parent": parent, "items": items}

def _get_home():
    return os.path.expanduser("~")

@router.get("/drive")
async def list_drives():
    """List available drives (Windows) or root (Linux/Mac)."""
    import string
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append({"name": f"{letter}:", "path": drive})
    if not drives:
        drives.append({"name": "/", "path": "/"})
    return {"drives": drives}

@router.post("/upload")
async def upload_file(file: bytes, target_dir: str = ""):
    """Upload a file to the specified directory."""
    import tempfile
    target = _safe_path(target_dir) if target_dir else tempfile.gettempdir()
    os.makedirs(target, exist_ok=True)
    # This endpoint receives raw file bytes
    # For actual file selection from local filesystem, use browse instead
    return {"ok": True, "target": target}

@router.get("/languages")
async def list_languages():
    """List available languages from dictionary."""
    import json as _json
    lang_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "languages.json")
    if not os.path.exists(lang_file):
        return {"languages": {}}
    with open(lang_file, "r", encoding="utf-8") as f:
        langs = _json.load(f)
    return {"languages": langs}


@router.post("/native-dialog")
async def native_file_dialog(req: dict):
    """Open system native file/folder dialog and return selected path(s)."""
    import threading
    
    dialog_type = req.get("type", "file")  # "file" or "folder"
    title = req.get("title", "Select")
    filetypes = req.get("filetypes", [])
    multiple = req.get("multiple", False)
    
    result = {"paths": [], "cancelled": True}
    
    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            
            if dialog_type == "folder":
                path = filedialog.askdirectory(title=title, mustexist=True)
                if path:
                    result["paths"] = [path]
                    result["cancelled"] = False
            else:
                tf = [(f[0], f[1]) for f in filetypes] if filetypes else [("All files", "*.*")]
                if multiple:
                    paths = filedialog.askopenfilenames(title=title, filetypes=tf)
                    if paths:
                        result["paths"] = list(paths)
                        result["cancelled"] = False
                else:
                    path = filedialog.askopenfilename(title=title, filetypes=tf)
                    if path:
                        result["paths"] = [path]
                        result["cancelled"] = False
            
            root.destroy()
        except Exception as e:
            result["error"] = str(e)
    
    t = threading.Thread(target=_run_dialog, daemon=True)
    t.start()
    t.join(timeout=30)  # 30s timeout
    
    # Backward compat: also return single path for old callers
    paths = result.get("paths", [])
    result["path"] = paths[0] if len(paths) == 1 else (paths[0] if paths else "")
    return result

@router.post("/native-save-dialog")
async def native_save_dialog(req: dict):
    """Open system native save file dialog and return selected path."""
    import threading
    
    title = req.get("title", "Save As")
    default_name = req.get("defaultName", "")
    filetypes = req.get("filetypes", [])
    
    result = {"path": "", "cancelled": True}
    
    def _run_dialog():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            
            tf = [(f[0], f[1]) for f in filetypes] if filetypes else [("All files", "*.*")]
            path = filedialog.asksaveasfilename(
                title=title, 
                initialfile=default_name,
                filetypes=tf
            )
            root.destroy()
            
            if path:
                result["path"] = path
                result["cancelled"] = False
        except Exception as e:
            result["error"] = str(e)
    
    t = threading.Thread(target=_run_dialog, daemon=True)
    t.start()
    t.join(timeout=30)
    
    return result

@router.get("/read")
async def read_file(path: str, task_id: Optional[str] = None):
    """Read file content as text."""
    import mimetypes
    safe = _stream_path(path, task_id)
    if not os.path.exists(safe):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.isfile(safe):
        raise HTTPException(status_code=400, detail="Not a file")
    
    # Check if it's a text file
    mime, _ = mimetypes.guess_type(safe)
    text_types = {".srt", ".ass", ".ssa", ".sub", ".txt", ".json", ".xml", ".vtt", ".sami", ".smi"}
    ext = os.path.splitext(safe)[1].lower()
    
    if ext not in text_types and (not mime or not mime.startswith("text/")):
        raise HTTPException(status_code=400, detail="Not a text file")
    
    try:
        with open(safe, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "path": safe}
    except UnicodeDecodeError:
        # Try with other encodings
        for enc in ["gbk", "latin-1"]:
            try:
                with open(safe, "r", encoding=enc) as f:
                    content = f.read()
                return {"content": content, "path": safe}
            except UnicodeDecodeError:
                continue
        raise HTTPException(status_code=400, detail="Unable to decode file")

@router.get("/stream")
async def stream_file(path: str, task_id: Optional[str] = None, request: Request = None):
    """Stream a file (video, audio, image) for preview with Range support."""
    from fastapi.responses import StreamingResponse
    import mimetypes

    safe = _stream_path(path, task_id)
    if not os.path.exists(safe):
        raise HTTPException(status_code=404, detail="File not found")
    if not os.path.isfile(safe):
        raise HTTPException(status_code=400, detail="Not a file")

    mime, _ = mimetypes.guess_type(safe)
    if not mime:
        mime = "application/octet-stream"

    file_size = os.path.getsize(safe)
    range_header = request.headers.get("range")

    if range_header:
        # 解析 Range: bytes=start-end
        range_start = 0
        range_end = file_size - 1
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            range_start = int(match.group(1))
            if match.group(2):
                range_end = int(match.group(2))
        content_length = range_end - range_start + 1

        def iter_range():
            with open(safe, "rb") as f:
                f.seek(range_start)
                remaining = content_length
                while remaining > 0:
                    chunk = f.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iter_range(),
            status_code=206,
            media_type=mime,
            headers={
                "Content-Range": f"bytes {range_start}-{range_end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
            },
        )

    return FileResponse(safe, media_type=mime)

@router.get("/video-info")
async def video_info(path: str, task_id: Optional[str] = None):
    """使用 ffprobe 获取视频基本信息（时长/帧率/分辨率），供去水印节点前端帧浏览使用。"""
    import json as _json

    safe = _stream_path(path, task_id)
    if not os.path.isfile(safe):
        raise HTTPException(status_code=404, detail="File not found")

    def _run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="ffprobe not found. Please install ffmpeg.")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail="ffprobe timed out")

    result = _run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", safe,
    ])
    if result.returncode != 0 or not result.stdout:
        raise HTTPException(status_code=500, detail="无法解析视频信息")
    try:
        info = _json.loads(result.stdout)
    except ValueError:
        raise HTTPException(status_code=500, detail="无法解析视频信息")
    streams = info.get("streams") or []
    fmt = info.get("format") or {}
    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    duration = 0.0
    try:
        duration = float(fmt.get("duration") or (vstream or {}).get("duration") or 0)
    except (ValueError, TypeError):
        duration = 0.0
    fps = 25.0
    if vstream:
        r_frame_rate = vstream.get("r_frame_rate") or vstream.get("avg_frame_rate") or ""
        if "/" in r_frame_rate:
            num, den = r_frame_rate.split("/", 1)
            try:
                fps = round(float(num) / float(den), 3)
            except (ValueError, ZeroDivisionError):
                fps = 25.0
    try:
        width = int((vstream or {}).get("width") or 0)
        height = int((vstream or {}).get("height") or 0)
    except (ValueError, TypeError):
        width, height = 0, 0
    return {"duration": duration, "fps": fps, "width": width, "height": height, "path": safe}

@router.post("/scan-audio")
async def scan_audio(body: dict):
    """Scan a directory for audio files."""
    path = body.get("path", "")
    recursive = body.get("recursive", False)
    audio_exts = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"}
    # 直接用原始路径，不做 realpath 转换（避免 Windows 盘符大小写问题）
    safe = os.path.normpath(path)
    if not os.path.isdir(safe):
        raise HTTPException(status_code=400, detail=f"Invalid directory: {safe}")

    files = []
    if recursive:
        for root, dirs, fnames in os.walk(safe):
            for f in fnames:
                if os.path.splitext(f)[1].lower() in audio_exts:
                    fp = os.path.join(root, f)
                    files.append({"name": f, "path": fp.replace("\\", "/"), "size": os.path.getsize(fp)})
    else:
        for f in os.listdir(safe):
            fp = os.path.join(safe, f)
            if os.path.isfile(fp) and os.path.splitext(f)[1].lower() in audio_exts:
                files.append({"name": f, "path": fp.replace("\\", "/"), "size": os.path.getsize(fp)})

    files.sort(key=lambda x: x["name"].lower())
    return {"files": files}

@router.post("/trim-audio")
async def trim_audio(body: dict):
    """Trim audio file using ffmpeg."""
    source = body.get("source_path", "")
    start = body.get("start", 0)
    end = body.get("end", 0)
    safe = _safe_path(source)
    if not os.path.isfile(safe):
        raise HTTPException(status_code=404, detail="Source file not found")

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cache_dir = os.path.join(project_root, "temp", "trim_audio")
    os.makedirs(cache_dir, exist_ok=True)
    ext = os.path.splitext(safe)[1]
    base_name = os.path.splitext(os.path.basename(safe))[0]
    out_name = f"{base_name}_trim_{uuid.uuid4().hex[:8]}{ext}"
    out_path = os.path.join(cache_dir, out_name)

    def _run_ffmpeg():
        cmd = ["ffmpeg", "-y", "-i", safe, "-ss", str(start), "-to", str(end), "-c", "copy", out_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg error: {result.stderr[:500]}")

    await asyncio.to_thread(_run_ffmpeg)
    return {"output_path": out_path.replace("\\", "/")}
