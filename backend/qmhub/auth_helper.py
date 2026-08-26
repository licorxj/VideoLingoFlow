"""qmhub API Key 自动管理 + 客户端构造。

共享模块：后端 API 路由和步骤文件都通过此模块获取 qmhub 客户端。
自动获取/创建并缓存 qmhub API Key（cbk_xxx 格式）。
"""
import json
from pathlib import Path

# API Key 缓存文件路径
_API_KEY_CACHE_FILE = Path(__file__).parent.parent / "data" / "workspace" / "pi-agent-config" / ".qmhub_api_key.json"


def _get_software_token() -> str:
    """从当前登录会话中获取软件 token。"""
    from backend.auth.cloud_auth_service import get_cloud_auth_service

    svc = get_cloud_auth_service()
    session = svc.get_session() or {}
    token = session.get("token") or ""
    if not token:
        raise RuntimeError("节点需要注册登录软件")
    return token


def _get_owner_id() -> str:
    """从当前登录会话中获取用户身份标识（用于绑定 API Key 缓存）。

    返回空字符串表示当前未登录。qmhub API Key 是账号级资源，
    更换登录账号后必须为当前账号重新创建，不能复用旧账号缓存的 Key。
    """
    try:
        from backend.auth.cloud_auth_service import get_cloud_auth_service

        svc = get_cloud_auth_service()
        session = svc.get_session() or {}
        user_info = session.get("user_info") or {}
        owner = user_info.get("id") or user_info.get("username") or ""
        return str(owner)
    except Exception:
        return ""


def _get_cached_api_key() -> str | None:
    """读取缓存的 qmhub API Key。

    仅当缓存归属账号与当前登录账号一致时才返回；否则视为无缓存，
    避免更换登录账号后误用旧账号的 Key。
    """
    try:
        if _API_KEY_CACHE_FILE.exists():
            data = json.loads(_API_KEY_CACHE_FILE.read_text(encoding="utf-8"))
            current_owner = _get_owner_id()
            cached_owner = str(data.get("owner") or "")
            # 未登录，或缓存归属账号与当前账号不一致时，不使用缓存
            if not current_owner or cached_owner != current_owner:
                return None
            return data.get("api_key")
    except Exception:
        pass
    return None


def _save_cached_api_key(api_key: str):
    """缓存 qmhub API Key（同时记录归属账号，用于换账号后失效旧缓存）。"""
    try:
        _API_KEY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _API_KEY_CACHE_FILE.write_text(
            json.dumps({"api_key": api_key, "owner": _get_owner_id()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def ensure_api_key() -> str:
    """获取或创建 qmhub API Key（cbk_xxx 格式）。

    优先从缓存读取；缓存不存在时用软件 token 调用 qmhub 后端创建新 Key。
    """
    # 1. 从缓存读取
    cached = _get_cached_api_key()
    if cached:
        return cached

    # 2. 用软件 token 创建新 Key
    token = _get_software_token()
    import requests

    # 创建新 Key
    r = requests.post(
        "https://www.licorxj.online/api/capability/keys",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"name": "videolingo-auto"},
        timeout=10,
    )
    if r.status_code != 200:
        raise RuntimeError(f"创建 qmhub API Key 失败: HTTP {r.status_code} {r.text[:200]}")

    body = r.json()
    if body.get("code") != 0:
        raise RuntimeError(f"创建 qmhub API Key 失败: {body}")

    raw_key = (body.get("data") or {}).get("raw_key")
    if not raw_key:
        raise RuntimeError("创建 qmhub API Key 失败：未返回 raw_key")

    # 缓存
    _save_cached_api_key(raw_key)
    return raw_key


def build_qmhub_client():
    """构造 qmhub 客户端，使用自动管理的 API Key。

    认证失败时自动清除缓存并重试一次。
    """
    from backend.qmhub.client import QmHubClient

    api_key = ensure_api_key()
    return QmHubClient(api_key=api_key)


def build_qmhub_client_with_retry():
    """构造 qmhub 客户端（用于 capability/invoke 等接口），认证失败时自动清除缓存并重试。"""
    try:
        return build_qmhub_client()
    except Exception:
        # 清除缓存后重试
        _save_cached_api_key("")
        return build_qmhub_client()


def build_mail_forwarding_client():
    """构造 qmhub 客户端（用于 mail-forwarding 接口），使用软件登录 token 认证。

    mail_forwarding 接口接受软件登录的 Bearer token，
    而 capability/invoke 接口要求 cbk_xxx 格式的 API Key。
    """
    from backend.qmhub.client import QmHubClient

    token = _get_software_token()
    return QmHubClient(api_key=token)
