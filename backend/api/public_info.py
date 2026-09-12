import asyncio

from fastapi import APIRouter, HTTPException

from backend.auth.cloud_auth_service import SOFTWARE_CODE, get_cloud_auth_service
from backend.config.config_manager import config


router = APIRouter(prefix="/api/public-info")

# 后端程序版本：取自配置 version（单一来源），缺省时回退内置值。
# 同时用于 OpenAPI 文档版本、/version 接口与 /api/public-info 的 local_version，
# 保证顶栏角标、About 页与接口文档展示同一个版本号。
APP_VERSION = str(config.get("version", "") or "2.0.0")

# 云端版本信息中可能的下载地址字段（不同时期服务端字段名不一致，统一兼容）
_DOWNLOAD_KEYS = ("update_url", "download_url", "downloadUrl", "url", "asset_url")


def _local_version() -> str:
    """本地版本：优先取配置 version，缺省回退到程序内置版本。"""
    return str(config.get("version", "") or APP_VERSION)


def _extract_download_url(update: dict | None) -> str:
    if not isinstance(update, dict):
        return ""
    for key in _DOWNLOAD_KEYS:
        value = update.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@router.get("")
async def get_public_info():
    client = get_cloud_auth_service()._client
    update_error = None
    announcement_error = None
    update = None
    announcements = []

    async def fetch_update():
        try:
            return client.check_update(SOFTWARE_CODE)
        except Exception as exc:
            nonlocal update_error
            update_error = str(exc)
            return None

    async def fetch_announcements():
        try:
            latest = client.get_latest_announcements(SOFTWARE_CODE)
            if not latest:
                latest = client.get_announcements(limit=10)
            return latest
        except Exception as exc:
            nonlocal announcement_error
            announcement_error = str(exc)
            return []

    update, announcements = await asyncio.gather(fetch_update(), fetch_announcements())
    if not isinstance(announcements, list):
        announcements = []
    return {
        "software_id": SOFTWARE_CODE,
        "local_version": _local_version(),
        "update": update,
        "announcements": announcements,
        "update_error": update_error,
        "announcement_error": announcement_error,
    }


@router.get("/announcements")
async def get_announcements():
    """仅获取项目公告（供「刷新公告」按钮使用，不涉及版本检查）。"""
    client = get_cloud_auth_service()._client
    try:
        latest = client.get_latest_announcements(SOFTWARE_CODE)
        if not latest:
            latest = client.get_announcements(limit=10)
        return {"announcements": latest if isinstance(latest, list) else [], "error": None}
    except Exception as exc:
        return {"announcements": [], "error": str(exc)}


@router.get("/version")
async def get_local_version():
    """本地版本信息（不访问云端，供顶栏版本角标即时展示）。

    与 /api/public-info 中的 local_version 同源，但不会触发云端更新检查与公告拉取，
    因此可以在页面启动时无感调用。
    """
    return {
        "version": _local_version(),
        "api_version": APP_VERSION,
        "software_id": SOFTWARE_CODE,
    }


@router.get("/download-url")
async def get_download_url():
    """从云端接口获取最新版本的下载地址（供前端「获取下载地址」按钮调用）。"""
    client = get_cloud_auth_service()._client
    try:
        update = client.check_update(SOFTWARE_CODE)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"获取云端版本失败：{exc}")
    url = _extract_download_url(update)
    if not url:
        raise HTTPException(status_code=404, detail="云端暂未提供下载地址")
    return {
        "version": (update or {}).get("version", ""),
        "download_url": url,
    }
