"""API routes for provider OAuth browser login (start / callback / status)."""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_key import ApiKey
from app.models.provider import Provider
from app.schemas.schemas import ApiKeyOut
from app.services import oauth_providers as op

router = APIRouter(prefix="/api/oauth", tags=["oauth-flow"])

_SUCCESS_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>LocalRouter</title>
<style>body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0b1220;
color:#e2e8f0;font-family:system-ui,sans-serif}}.c{{text-align:center}}</style></head>
<body><div class="c"><h2>✓ 授权成功</h2><p>令牌已保存到 LocalRouter，可关闭此窗口</p></div></body></html>"""

_FAILURE_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>LocalRouter</title>
<style>body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0b1220;
color:#fca5a5;font-family:system-ui,sans-serif}}.c{{text-align:center}}</style></head>
<body><div class="c"><h2>授权失败</h2><p>{error}</p></div></body></html>"""


class OauthStart(BaseModel):
    provider_id: int
    profile_id: str = ""  # defaults to the provider's auth_type


@router.post("/start")
async def oauth_start(data: OauthStart, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, data.provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    profile_id = data.profile_id or provider.auth_type
    if not profile_id or profile_id == "api_key":
        raise HTTPException(400, "This provider is not configured for OAuth login (auth_type is 'api_key')")
    profile = op.get_profile(profile_id)
    if not profile:
        raise HTTPException(400, f"Unknown OAuth profile: {profile_id}")
    try:
        flow = op.start_session(data.provider_id, profile_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Failed to contact the OAuth provider: {str(e)[:200]}")
    return {**flow, "profile_id": profile_id, "label": profile.get("label", profile_id)}


@router.get("/callback/{session_id}")
async def oauth_callback(session_id: str, code: str = "", state: str = "", error: str = ""):
    session = op.get_session(session_id)
    if not session:
        return HTMLResponse(_FAILURE_PAGE.format(error="会话已过期，请重新发起登录"), status_code=410)
    if error:
        op.fail_session(session_id, error)
        return HTMLResponse(_FAILURE_PAGE.format(error=error), status_code=200)
    if state != session["state"] or not code:
        op.fail_session(session_id, "state mismatch")
        return HTMLResponse(_FAILURE_PAGE.format(error="state 校验失败"), status_code=400)

    profile = op.get_profile(session["profile_id"])
    try:
        tokens = await op.exchange_code(profile, code, session)
        from app.database import async_session
        async with async_session() as db:
            key = await op.store_oauth_key(db, session["provider_id"], session["profile_id"], tokens)
        op.complete_session(session_id, key.id)
    except Exception as e:
        op.fail_session(session_id, str(e)[:200])
        return HTMLResponse(_FAILURE_PAGE.format(error=str(e)[:200]), status_code=200)
    return HTMLResponse(_SUCCESS_PAGE)


@router.get("/status/{session_id}")
async def oauth_status(session_id: str, db: AsyncSession = Depends(get_db)):
    session = op.get_session(session_id)
    if not session:
        return {"status": "expired"}
    if session.get("flow") in ("device", "codebuddy") and session["status"] == "pending":
        # Device flows: each status poll drives one token-poll attempt upstream
        result = await op.poll_device_session(session_id, db)
        result.setdefault("user_code", session.get("user_code", ""))
        result.setdefault("verification_uri", session.get("verification_uri", ""))
        return result
    return {"status": session["status"], "key_id": session["key_id"], "error": session["error"]}


@router.get("/profiles")
async def oauth_profiles():
    return op.load_profiles()


@router.post("/refresh/{key_id}", response_model=ApiKeyOut)
async def oauth_refresh(key_id: int, db: AsyncSession = Depends(get_db)):
    api_key = await db.get(ApiKey, key_id)
    if not api_key or not api_key.oauth_profile:
        raise HTTPException(404, "OAuth key not found")
    await op.ensure_fresh_token(db, api_key, force=True)
    await db.refresh(api_key)
    from app.routers.api_keys import _key_to_out
    return _key_to_out(api_key)
