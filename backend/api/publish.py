"""Publish API routes - proxy to social-auto-upload backend (port 5409)."""
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from backend.publish.platform_config import PLATFORMS
from backend.publish.mcp_client import get_publish_client

router = APIRouter()


# ─── Request Models ───

class PublishVideoRequest(BaseModel):
    type: int
    title: str
    file_paths: list[str]
    account_id: Optional[str] = None
    account_list: Optional[list[str]] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    thumbnail: Optional[str] = None
    thumbnail_landscape: Optional[str] = None
    thumbnail_portrait: Optional[str] = None
    is_draft: bool = False
    schedule_time: Optional[str] = None
    is_original: Optional[bool] = None
    audience: Optional[str] = None
    ai_content: Optional[str] = None
    hotspot: Optional[str] = None
    mix_id: Optional[str] = None


class CreateDraftRequest(BaseModel):
    type: str = "video"
    draft_data: dict = {}


class UpdateDraftRequest(BaseModel):
    draft_data: dict = {}


class BatchIdsRequest(BaseModel):
    draft_ids: list[int] = []


class BatchHistoryRequest(BaseModel):
    batch_ids: list[str] = []


class TagRequest(BaseModel):
    name: str
    color: Optional[str] = None


class AccountTagsRequest(BaseModel):
    tag_ids: list[int] = []


class BatchAccountTagsRequest(BaseModel):
    account_ids: list[int] = []
    tag_ids: list[int] = []


class SettingsRequest(BaseModel):
    pass  # Accepts any dict


# ═══════════════════════════════════════════
# Platforms
# ═══════════════════════════════════════════

@router.get("/platforms")
async def list_platforms():
    """List all supported publishing platforms with metadata."""
    return list(PLATFORMS.values())


# ═══════════════════════════════════════════
# Accounts
# ═══════════════════════════════════════════

@router.get("/accounts")
async def list_accounts(type: Optional[str] = None):
    """List all accounts, optionally filtered by platform type."""
    try:
        client = get_publish_client()
        accounts = client.list_accounts()
        if type:
            type_int = int(type)
            accounts = [a for a in accounts if a.get("type") == type_int or str(a.get("type")) == type]
        return {"accounts": accounts}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to list accounts: {e}")


@router.get("/accounts/all")
async def list_all_accounts():
    """List all accounts formatted for frontend selection."""
    try:
        client = get_publish_client()
        accounts = client.list_accounts()
        result = []
        for acc in accounts:
            acc_type = acc.get("type", 0)
            platform = PLATFORMS.get(acc_type, {})
            platform_name = platform.get("name", f"平台{acc_type}")
            acc_name = acc.get("name") or acc.get("account_name") or acc.get("id", "未知")
            acc_id = acc.get("id") or acc.get("account_id") or ""
            result.append({
                "value": str(acc_id),
                "label": f"{platform_name} - {acc_name}",
                "type": acc_type,
                "name": acc_name,
                "platform": platform_name,
            })
        if not result:
            return {"options": [], "message": "请到发布标签页添加账号"}
        return {"options": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to list accounts: {e}")


@router.get("/accounts/valid")
async def list_valid_accounts():
    """List accounts with cookie validity check."""
    try:
        client = get_publish_client()
        return {"accounts": client.get_valid_accounts()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/accounts/{account_id}/check")
async def check_account(account_id: str):
    """Check if account cookie is valid."""
    try:
        client = get_publish_client()
        return client.check_account(account_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to check account: {e}")


@router.get("/accounts/{account_id}/delete")
async def delete_account(account_id: str):
    """Delete an account."""
    try:
        client = get_publish_client()
        return client.delete_account(account_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to delete account: {e}")


@router.post("/accounts/{account_id}/sync")
async def sync_profile(account_id: str):
    """Sync account avatar and nickname from platform."""
    try:
        client = get_publish_client()
        return client.sync_profile(account_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════
# Tags
# ═══════════════════════════════════════════

@router.get("/tags")
async def list_tags():
    """Get all tags."""
    try:
        return get_publish_client().list_tags()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/tags")
async def create_tag(req: TagRequest):
    """Create a tag."""
    try:
        return get_publish_client().create_tag(req.name, req.color)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int):
    """Delete a tag."""
    try:
        return get_publish_client().delete_tag(tag_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/accounts/{account_id}/tags")
async def get_account_tags(account_id: int):
    """Get tags for an account."""
    try:
        return get_publish_client().get_account_tags(account_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/accounts/{account_id}/tags")
async def set_account_tags(account_id: int, req: AccountTagsRequest):
    """Set tags for an account."""
    try:
        return get_publish_client().set_account_tags(account_id, req.tag_ids)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/accounts/batch/tags")
async def batch_set_account_tags(req: BatchAccountTagsRequest):
    """Batch append tags to multiple accounts."""
    try:
        return get_publish_client().batch_set_account_tags(req.account_ids, req.tag_ids)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════
# Video Publishing
# ═══════════════════════════════════════════

@router.post("/video")
async def publish_video(req: PublishVideoRequest):
    """Publish a video to a platform."""
    try:
        client = get_publish_client()
        kwargs = {}
        for field in ("is_original", "audience", "ai_content", "hotspot", "mix_id"):
            val = getattr(req, field, None)
            if val is not None:
                kwargs[field] = val

        result = client.publish_video(
            type=req.type,
            title=req.title,
            file_paths=req.file_paths,
            account_id=req.account_id,
            account_list=req.account_list,
            description=req.description,
            tags=req.tags,
            thumbnail=req.thumbnail,
            thumbnail_landscape=req.thumbnail_landscape,
            thumbnail_portrait=req.thumbnail_portrait,
            is_draft=req.is_draft,
            schedule_time=req.schedule_time,
            **kwargs,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Publish failed: {e}")


# ═══════════════════════════════════════════
# Materials
# ═══════════════════════════════════════════

@router.post("/materials/upload")
async def upload_material(file: UploadFile = File(...)):
    """Upload a file to the materials system."""
    try:
        client = get_publish_client()
        import tempfile, os
        suffix = os.path.splitext(file.filename or "")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        try:
            result = client.upload_material(tmp_path)
            return result
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upload failed: {e}")


@router.get("/materials")
async def list_materials(type: str = "all", keyword: str = "", page: int = 1, page_size: int = 20):
    """List materials."""
    try:
        return get_publish_client().list_materials(type, keyword, page, page_size)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/materials/{material_id}")
async def get_material(material_id: str):
    """Get a single material."""
    try:
        return get_publish_client().get_material(material_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str):
    """Delete a material."""
    try:
        return get_publish_client().delete_material(material_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/materials/{material_id}/probe")
async def probe_material(material_id: str):
    """Probe material for duration/size."""
    try:
        return get_publish_client().probe_material(material_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════
# Drafts
# ═══════════════════════════════════════════

@router.get("/drafts")
async def list_drafts(type: str = "video"):
    """List drafts."""
    try:
        return get_publish_client().list_drafts(type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/draft")
async def create_draft(req: CreateDraftRequest):
    """Create a draft."""
    try:
        return get_publish_client().create_draft(req.type, req.draft_data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: str):
    """Get draft details."""
    try:
        return get_publish_client().get_draft(draft_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/drafts/{draft_id}")
async def update_draft(draft_id: str, req: UpdateDraftRequest):
    """Update a draft."""
    try:
        return get_publish_client().update_draft(draft_id, req.draft_data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/drafts/{draft_id}")
async def delete_draft(draft_id: str):
    """Delete a draft."""
    try:
        return get_publish_client().delete_draft(draft_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/drafts/batch-publish")
async def batch_publish_drafts(req: BatchIdsRequest):
    """Batch publish drafts."""
    try:
        return get_publish_client().batch_publish_drafts(req.draft_ids)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/drafts/batch")
async def batch_delete_drafts(req: BatchIdsRequest):
    """Batch delete drafts."""
    try:
        return get_publish_client().batch_delete_drafts(req.draft_ids)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════
# Tasks
# ═══════════════════════════════════════════

@router.get("/tasks")
async def list_tasks(status: str = "all", page: int = 1, page_size: int = 20):
    """List publish tasks."""
    try:
        return get_publish_client().list_tasks(status, page, page_size)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get task status."""
    try:
        return get_publish_client().get_task_status(task_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a task."""
    try:
        return get_publish_client().cancel_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    """Retry a failed task."""
    try:
        return get_publish_client().retry_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════
# History & Stats
# ═══════════════════════════════════════════

@router.get("/stats")
async def get_stats():
    """Get publish statistics."""
    try:
        return get_publish_client().get_publish_stats()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/queue")
async def get_queue():
    """Get queue status."""
    try:
        return get_publish_client().get_queue_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/history")
async def get_history(
    platform: Optional[str] = None,
    status: Optional[str] = None,
    time_range: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    """Get publish history."""
    try:
        return get_publish_client().get_publish_history(platform, status, time_range, page, page_size)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/history/{batch_id}")
async def get_history_detail(batch_id: str):
    """Get a single publish batch detail."""
    try:
        return get_publish_client().get_history_detail(batch_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/history/{batch_id}")
async def delete_history(batch_id: str):
    """Delete a single publish history record."""
    try:
        return get_publish_client().delete_history(batch_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/history/batch")
async def batch_delete_history(req: BatchHistoryRequest):
    """Batch delete publish history."""
    try:
        return get_publish_client().batch_delete_history(req.batch_ids)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════
# Settings
# ═══════════════════════════════════════════

@router.get("/settings")
async def get_settings():
    """Get system settings."""
    try:
        return get_publish_client().get_settings()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.put("/settings")
async def update_settings(settings: dict):
    """Update system settings."""
    try:
        return get_publish_client().update_settings(settings)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════
# Templates
# ═══════════════════════════════════════════

@router.get("/templates")
async def get_templates(type: str = "video"):
    """Get reusable publish config templates."""
    try:
        return get_publish_client().get_publish_templates(type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ═══════════════════════════════════════════
# Health & System
# ═══════════════════════════════════════════

@router.get("/health")
async def health_check():
    """Check if the publish backend is available."""
    try:
        client = get_publish_client()
        available = client.is_available()
        return {"available": available}
    except Exception as e:
        return {"available": False, "error": str(e)}


@router.get("/system-info")
async def system_info():
    """Get system info (version, cache size)."""
    try:
        return get_publish_client().get_system_info()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/cache/clear")
async def clear_cache():
    """Clear backend caches."""
    try:
        return get_publish_client().clear_cache()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


import threading
import time
import shutil

_update_status_lock = threading.Lock()
_update_status = {
    "status": "idle",
    "message": "",
    "updated_at": 0,
}


def _get_exec_cmd(cmd_name: str) -> str:
    import os
    found = shutil.which(cmd_name)
    if found:
        return found
    if os.name == "nt":
        found_cmd = shutil.which(f"{cmd_name}.cmd") or shutil.which(f"{cmd_name}.exe") or shutil.which(f"{cmd_name}.bat")
        if found_cmd:
            return found_cmd
        if cmd_name == "git":
            for p in [
                r"C:\Program Files\Git\cmd\git.exe",
                r"C:\Program Files (x86)\Git\cmd\git.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
            ]:
                if os.path.exists(p):
                    return p
    return cmd_name


def _run_async_update_project():
    global _update_status
    import subprocess
    import os

    with _update_status_lock:
        _update_status["status"] = "updating"
        _update_status["message"] = "正在拉取最新代码..."
        _update_status["updated_at"] = time.time()

    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    project_dir = os.path.join(root_dir, "thirdparty", "social-auto-upload-web-ui")
    repo_url = "https://github.com/DevilJie/social-auto-upload-web-ui.git"

    is_win = os.name == "nt"
    git_bin = _get_exec_cmd("git")

    try:
        if not os.path.exists(project_dir):
            os.makedirs(project_dir, exist_ok=True)

        git_dir = os.path.join(project_dir, ".git")
        if not os.path.exists(git_dir):
            # 分发版：先释放随仓库携带的 git 归档（保留原项目历史与更新能力）
            try:
                import sys as _sys
                subprocess.run(
                    [_sys.executable, os.path.join(root_dir, "thirdparty", "git_restore.py")],
                    capture_output=True, text=True, timeout=180,
                )
            except Exception as _e:
                print(f"[UpdateSocialProject] git_restore skipped/error: {_e}")
            # 仍无 .git（归档缺失等）再全新初始化
            if not os.path.exists(git_dir):
                subprocess.run([git_bin, "init"], cwd=project_dir, capture_output=True, timeout=30, shell=is_win)
                subprocess.run([git_bin, "remote", "add", "origin", repo_url], cwd=project_dir, capture_output=True, timeout=30, shell=is_win)
                subprocess.run([git_bin, "remote", "set-url", "origin", repo_url], cwd=project_dir, capture_output=True, timeout=30, shell=is_win)

        # 拉取远端最新代码（自动匹配当前分支，不写死 master）
        subprocess.run([git_bin, "fetch", "origin"], cwd=project_dir, capture_output=True, text=True, timeout=120, shell=is_win)
        branch = subprocess.run(
            [git_bin, "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir, capture_output=True, text=True, timeout=30, shell=is_win,
        ).stdout.strip() or "master"
        if branch in ("HEAD", ""):
            branch = "master"

        # 强制同步到远端最新（覆盖本地修改，适合第三方嵌入场景；数据库在 .gitignore 内不受影响）
        res = subprocess.run(
            [git_bin, "reset", "--hard", f"origin/{branch}"],
            cwd=project_dir, capture_output=True, text=True, timeout=120, shell=is_win,
        )
        if res.returncode != 0:
            raise Exception(f"git 同步失败: {res.stderr or res.stdout}")

        # 是否同时重新构建 Social 前端界面（config.yaml -> social_update.rebuild_frontend）
        # 默认 false：仅更新代码与后端依赖并重启后端，保护用户对前端做的微调。
        rebuild_frontend = False
        try:
            from backend.config.config_manager import config as app_config
            rebuild_frontend = bool(app_config.get("social_update.rebuild_frontend", False))
        except Exception as e:
            print(f"[UpdateSocialProject] Read social_update config skipped/error: {e}")

        # 始终增量更新后端 Python 依赖（若第三方更新了 requirements.txt），不影响前端微调
        with _update_status_lock:
            _update_status["message"] = "正在更新后端 Python 依赖..."
            _update_status["updated_at"] = time.time()
        _update_backend_python_deps(project_dir, is_win)

        if rebuild_frontend:
            # 静态托管模式：代码更新后必须重新构建 dist，前端才会生效。
            # 构建期间先停掉前端静态服务，避免读到半写入的文件。
            try:
                from backend.manager import stop_social_frontend
                stop_social_frontend()
            except Exception as e:
                print(f"[UpdateSocialProject] Stop frontend skipped/error: {e}")

            # 重建前先备份当前（可能含用户微调的）前端 dist，失败可回滚
            _backup_frontend_dist(project_dir)

            with _update_status_lock:
                _update_status["message"] = "代码已拉取，正在重新构建前端..."
                _update_status["updated_at"] = time.time()

            frontend_dir = os.path.join(project_dir, "frontend")
            npm_cmd = _get_exec_cmd("npm")
            if not os.path.isdir(os.path.join(frontend_dir, "node_modules")):
                subprocess.run(
                    [npm_cmd, "install", "--prefer-offline", "--registry=https://registry.npmmirror.com"],
                    cwd=frontend_dir, capture_output=True, text=True, timeout=300, shell=is_win,
                )
            res = subprocess.run(
                [npm_cmd, "run", "build"],
                cwd=frontend_dir, capture_output=True, text=True, timeout=600, shell=is_win,
            )
            if res.returncode != 0:
                raise Exception(f"前端构建失败: {(res.stdout or res.stderr)[-2000:]}")

        with _update_status_lock:
            _update_status["message"] = "代码更新完成，正在重启后端服务..."
            _update_status["updated_at"] = time.time()

        try:
            if rebuild_frontend:
                # 重建前端时同步重建并重启 MCP（TS 需重新编译），再重启前后端
                _rebuild_and_restart_mcp(project_dir, is_win)
                from backend.manager import restart_social_backend_only, start_social_frontend
                restart_social_backend_only()
                start_social_frontend()
            else:
                # 默认：仅重启后端，完全不动前端静态页面与 MCP，保护用户微调
                from backend.manager import restart_social_backend_only
                restart_social_backend_only()
        except Exception as e:
            print(f"[UpdateSocialProject] Restart skipped/error: {e}")

        with _update_status_lock:
            _update_status["status"] = "success"
            _update_status["message"] = (
                "第三方项目 git 更新及前端重新构建已成功完成！"
                if rebuild_frontend else
                "第三方项目 git 更新已成功完成！（未重新构建前端，如需更新界面请在 config.yaml 中设置 social_update.rebuild_frontend: true）"
            )
            _update_status["updated_at"] = time.time()

    except Exception as e:
        with _update_status_lock:
            _update_status["status"] = "error"
            _update_status["message"] = f"更新失败: {str(e)}"
            _update_status["updated_at"] = time.time()


def _update_backend_python_deps(project_dir: str, is_win: bool):
    """增量更新第三方后端 Python 依赖（仅当 requirements.txt 变更时重装）。"""
    import hashlib
    import shutil

    backend_dir = os.path.join(project_dir, "backend")
    req_file = os.path.join(backend_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return
    venv_dir = os.path.join(backend_dir, ".venv")
    venv_python = (
        os.path.join(venv_dir, "Scripts", "python.exe") if is_win
        else os.path.join(venv_dir, "bin", "python")
    )
    if not os.path.isfile(venv_python):
        # venv 不存在则由 manager 的启动流程负责创建，这里跳过
        print("[UpdateSocialProject] venv 不存在，跳过依赖更新（下次启动将自动创建）")
        return

    # 基于 requirements.txt 内容哈希判断是否需要更新，避免每次更新都重装
    try:
        with open(req_file, "rb") as f:
            req_hash = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return
    hash_file = os.path.join(backend_dir, ".sau_req_hash")
    old_hash = ""
    if os.path.isfile(hash_file):
        try:
            old_hash = open(hash_file, "r").read().strip()
        except Exception:
            old_hash = ""
    if req_hash == old_hash:
        print("[UpdateSocialProject] 后端依赖无变更，跳过")
        return

    pip = (
        os.path.join(venv_dir, "Scripts", "pip.exe") if is_win
        else os.path.join(venv_dir, "bin", "pip")
    )
    try:
        subprocess.run(
            [pip, "install", "-r", req_file, "--no-cache-dir", "-i", "https://mirrors.aliyun.com/pypi/simple/"],
            cwd=backend_dir, capture_output=True, text=True, timeout=600, shell=is_win,
        )
        with open(hash_file, "w") as f:
            f.write(req_hash)
        print("[UpdateSocialProject] 后端 Python 依赖已更新")
    except Exception as e:
        print(f"[UpdateSocialProject] 后端依赖更新失败（可忽略，下次启动重试）: {e}")


def _rebuild_and_restart_mcp(project_dir: str, is_win: bool):
    """重新编译并重启 backend-mcp（仅在重建前端时调用）。"""
    mcp_dir = os.path.join(project_dir, "backend-mcp")
    if not os.path.isdir(mcp_dir):
        return
    npm_cmd = _get_exec_cmd("npm")
    try:
        subprocess.run(
            [npm_cmd, "install", "--prefer-offline", "--registry=https://registry.npmmirror.com"],
            cwd=mcp_dir, capture_output=True, text=True, timeout=300, shell=is_win,
        )
        subprocess.run(
            [npm_cmd, "run", "build"],
            cwd=mcp_dir, capture_output=True, text=True, timeout=300, shell=is_win,
        )
        from backend.manager import restart_social_mcp_only
        restart_social_mcp_only()
        print("[UpdateSocialProject] MCP 已重新编译并重启")
    except Exception as e:
        print(f"[UpdateSocialProject] MCP 重建/重启失败（可忽略）: {e}")


def _backup_frontend_dist(project_dir: str, keep: int = 5):
    """重建前端前备份当前 dist（可能含用户微调），按时间戳归档并保留最近 keep 份。

    备份目录：<project>/frontend/.dist_backups/dist_<YYYYMMDD_HHMMSS>
    回滚方式：将对应备份目录复制回 frontend/dist 即可。
    """
    import shutil as _shutil

    frontend_dir = os.path.join(project_dir, "frontend")
    dist_dir = os.path.join(frontend_dir, "dist")
    if not os.path.isdir(dist_dir):
        print("[UpdateSocialProject] 无 dist 可备份，跳过（首次构建）")
        return

    backup_root = os.path.join(frontend_dir, ".dist_backups")
    os.makedirs(backup_root, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_root, f"dist_{stamp}")
    try:
        _shutil.copytree(dist_dir, dest)
        print(f"[UpdateSocialProject] 已备份前端 dist -> {dest}")
    except Exception as e:
        print(f"[UpdateSocialProject] 备份前端 dist 失败（可忽略）: {e}")
        return

    # 仅保留最近 keep 份，删除最旧的
    try:
        subs = sorted(
            (d for d in os.listdir(backup_root)
             if d.startswith("dist_") and os.path.isdir(os.path.join(backup_root, d))),
            key=lambda d: os.path.getmtime(os.path.join(backup_root, d)),
        )
        for old in subs[:-keep]:
            _shutil.rmtree(os.path.join(backup_root, old), ignore_errors=True)
    except Exception as e:
        print(f"[UpdateSocialProject] 清理旧备份失败（可忽略）: {e}")


@router.post("/update-project")
async def update_social_project():
    """Start async git pull & build task for thirdparty/social-auto-upload-web-ui."""
    with _update_status_lock:
        if _update_status["status"] == "updating":
            return {"code": 200, "msg": "更新正在后台进行中..."}

    t = threading.Thread(target=_run_async_update_project, daemon=True)
    t.start()
    return {"code": 200, "msg": "更新任务已在后台启动！"}


@router.get("/update-status")
async def get_social_project_update_status():
    """Get update task status."""
    with _update_status_lock:
        return dict(_update_status)
