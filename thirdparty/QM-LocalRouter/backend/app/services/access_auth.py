"""Inbound access auth and endpoint group registry (OmniRoute-style).

Two mechanisms, mirroring OmniRoute's design:
- Bearer key auth on every /v1 endpoint, controlled by the `auth_mode` setting
  ("open" = no auth, "virtual_key" = requests must carry an active ClientKey).
- Key-in-path aliases (/k/{key}/v1/...) for clients that cannot attach
  custom headers (some IDE plugins, tools with fixed webhook URLs, etc.).
"""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.client_key import ClientKey
from app.routers.settings import _get_settings
from app.services import browser_auth

# Endpoint groups exposed by the router; each can be toggled in settings.
ENDPOINT_GROUPS: dict[str, list[tuple[str, str]]] = {
    "openai": [
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/completions"),
        ("GET", "/v1/models"),
        ("POST", "/v1/embeddings"),
    ],
    "media": [
        ("POST", "/v1/audio/transcriptions"),
        ("POST", "/v1/images/generations"),
        ("POST", "/v1/audio/speech"),
        ("POST", "/v1/videos"),
        ("GET", "/v1/videos/{task_id}"),
    ],
    "multi": [
        ("POST", "/v1/multi/chat/completions"),
        ("POST", "/v1/multi/stream/chat/completions"),
    ],
    "alias": [
        ("POST", "/k/{client_key}/v1/chat/completions"),
        ("GET", "/k/{client_key}/v1/models"),
    ],
}


def _match_pattern(pattern: str, path: str) -> bool:
    """Match a route pattern like /v1/videos/{task_id} against a concrete path."""
    p_parts, a_parts = pattern.strip("/").split("/"), path.strip("/").split("/")
    if len(p_parts) != len(a_parts):
        return False
    return all(pp.startswith("{") or pp == ap for pp, ap in zip(p_parts, a_parts))


def resolve_endpoint_group(method: str, path: str) -> str | None:
    for group, endpoints in ENDPOINT_GROUPS.items():
        for m, pattern in endpoints:
            if m == method and _match_pattern(pattern, path):
                return group
    return None


def _extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    xkey = request.headers.get("x-api-key", "")
    if xkey:
        return xkey.strip()
    return (request.query_params.get("key") or "").strip()


def _auth_error(status: int, message: str) -> HTTPException:
    # OpenAI-style error envelope so SDKs surface the message cleanly
    return HTTPException(status_code=status, detail={"error": {"message": message, "type": "invalid_request_error", "code": "invalid_api_key"}})


async def _find_active_client_key(db: AsyncSession, key_value: str) -> ClientKey | None:
    result = await db.execute(
        select(ClientKey).where(ClientKey.key_value == key_value, ClientKey.is_active == True)  # noqa: E712
    )
    return result.scalar_one_or_none()


async def verify_client_auth(request: Request, db: AsyncSession = Depends(get_db)):
    settings = _get_settings()

    group = resolve_endpoint_group(request.method, request.url.path)
    if group and not (settings.get("enabled_groups") or {}).get(group, True):
        raise HTTPException(status_code=404, detail="This endpoint is disabled in endpoint settings")

    mode = settings.get("auth_mode", "open")
    if mode == "open":
        return

    token = _extract_bearer_token(request)
    if not token:
        hint = (
            "Missing credentials. Pass a virtual key via 'Authorization: Bearer <key>' or log in at /oauth/authorize."
            if mode == "oauth"
            else "Missing API key. Pass it via 'Authorization: Bearer <key>' or 'x-api-key' header."
        )
        raise _auth_error(401, hint)

    # 1) Static virtual key (also honored in oauth mode)
    key = await _find_active_client_key(db, token)
    if key:
        key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        return

    # 2) JWT issued by browser login (/oauth/token or /api/auth/login)
    if browser_auth.verify_access_token(token):
        return

    raise _auth_error(401, "Invalid or disabled API key.")


async def verify_alias_client_key(client_key: str, db: AsyncSession = Depends(get_db)):
    """Auth for key-in-path aliases: the key itself is the credential."""
    key = await _find_active_client_key(db, client_key)
    if not key:
        raise _auth_error(401, "Invalid or disabled API key.")
    key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
