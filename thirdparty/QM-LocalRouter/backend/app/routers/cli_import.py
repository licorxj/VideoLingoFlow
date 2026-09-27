"""Local CLI credential import: detect / paste / import for CLI-managed platforms."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_key import ApiKey
from app.models.provider import Provider
from app.schemas.schemas import ApiKeyOut
from app.services import local_cli

router = APIRouter(prefix="/api/cli", tags=["cli-import"])


@router.get("/platforms")
async def cli_platforms():
    platforms = local_cli.load_cli_platforms()
    out = []
    for pid, p in platforms.items():
        out.append({
            "id": pid,
            "label": p["label"],
            "import_modes": p["import_modes"],
            "detect_paths": [tpl for tpl, _, _ in p.get("detect_paths", []) if tpl],
            "upstream": p.get("upstream") or {},
            "refresh_supported": bool(p.get("refresh")),
            "token_lifetime_days": p.get("token_lifetime_days"),
        })
    return out


@router.post("/detect")
async def cli_detect(data: dict):
    platform_id = str(data.get("platform", ""))
    candidates = local_cli.detect_credentials(platform_id)
    if not candidates and platform_id == "amazon-q":
        # Kiro may store its SSO cache under other roots; hint the user to paste
        pass
    return {"platform": platform_id, "candidates": candidates}


class CliImport(BaseModel):
    platform: str
    provider_id: int = 0          # 0 => auto-create a provider for this platform
    token: str = ""                # pasted access/JWT token (paste mode)
    refresh_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    region: str = ""
    code: str = ""                 # paste-back: auth code or full callback URL (cline/antigravity)
    redirect_uri: str = ""         # paste-back: the redirect_uri used in the authorize request
    detected_path: str = ""        # import mode from a detected local file


@router.post("/import", response_model=ApiKeyOut, status_code=201)
async def cli_import(data: CliImport, db: AsyncSession = Depends(get_db)):
    platform = local_cli.get_cli_platform(data.platform)
    if not platform:
        raise HTTPException(404, f"Unknown CLI platform: {data.platform}")

    # Paste-back browser flow: exchange the auth code per platform
    if data.code:
        from app.services import local_cli as lc
        from urllib.parse import urlparse
        code = lc.parse_code_from_paste(data.code)
        redirect_uri = data.redirect_uri
        if not redirect_uri and data.code.strip().startswith("http"):
            parsed = urlparse(data.code.strip())
            redirect_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"  # Google requires the exact authorize redirect_uri
        if not redirect_uri:
            redirect_uri = f"http://127.0.0.1:12002/api/cli/callback/paste"
        provider_id = await lc.ensure_provider(db, data.platform, data.provider_id)
        if data.platform == "cline":
            key = await lc.complete_cline_code(provider_id, code, redirect_uri, db)
        elif data.platform == "antigravity":
            if not (data.client_id and data.client_secret):
                raise HTTPException(400, "antigravity code exchange needs client_id and client_secret")
            key = await lc.complete_antigravity_code(provider_id, code, data.client_id,
                                                     data.client_secret, data.redirect_uri or redirect_uri, db)
        else:
            raise HTTPException(400, f"Paste-back code not supported for platform '{data.platform}'")
        from app.routers.api_keys import _key_to_out
        return _key_to_out(key)

    # Build the credential payload
    if data.detected_path:
        try:
            credential = local_cli.extract_credentials(data.platform, data.detected_path)
        except ValueError as e:
            raise HTTPException(400, str(e))
    else:
        credential = {}
        if data.token:
            credential["access_token"] = data.token.strip()
        if data.refresh_token:
            credential["refresh_token"] = data.refresh_token.strip()
        if data.client_id:
            credential["client_id"] = data.client_id.strip()
        if data.client_secret:
            credential["client_secret"] = data.client_secret.strip()
        if data.region:
            credential["region"] = data.region.strip()
        if not credential:
            if data.platform == "opencode":
                credential = {"access_token": "opencode-free"}  # public endpoint, no key needed
            else:
                raise HTTPException(400, "No credential provided (token or refresh_token)")

    # Resolve or auto-create the provider (deduped by auth_type)
    provider_id = await local_cli.ensure_provider(db, data.platform, data.provider_id)
    provider = await db.get(Provider, provider_id)

    try:
        key = await local_cli.store_cli_key(db, provider_id, data.platform, credential)
    except ValueError as e:
        raise HTTPException(400, str(e))

    from app.routers.api_keys import _key_to_out
    return _key_to_out(key)


_SUCCESS_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>LocalRouter</title>
<style>body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0b1220;
color:#e2e8f0;font-family:system-ui,sans-serif}}.c{{text-align:center}}</style></head>
<body><div class="c"><h2>✓ 授权成功</h2><p>令牌已保存到 LocalRouter，可关闭此窗口</p></div></body></html>"""

_FAILURE_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>LocalRouter</title>
<style>body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0b1220;
color:#fca5a5;font-family:system-ui,sans-serif}}.c{{text-align:center}}</style></head>
<body><div class="c"><h2>授权失败</h2><p>{error}</p></div></body></html>"""


class CliBrowserStart(BaseModel):
    platform: str
    provider_id: int = 0
    client_id: str = ""      # antigravity: from detect/paste
    client_secret: str = ""


@router.post("/browser-start")
async def cli_browser_start(data: CliBrowserStart):
    from app.services import local_cli as lc
    try:
        if data.platform == "cline":
            return lc.start_cline_session(data.provider_id)
        if data.platform == "amazon-q":
            return lc.start_amazonq_session(data.provider_id)
        if data.platform == "antigravity":
            return lc.start_antigravity_session(data.provider_id, data.client_id, data.client_secret)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Failed to start browser flow: {str(e)[:200]}")
    raise HTTPException(400, f"No browser flow for platform '{data.platform}'")


@router.get("/callback/{session_id}")
async def cli_callback(session_id: str, code: str = "", error: str = "", db: AsyncSession = Depends(get_db)):
    from app.services import local_cli as lc
    session = lc.get_cli_session(session_id)
    if not session:
        return HTMLResponse(_FAILURE_PAGE.format(error="会话已过期，请重新发起授权"), status_code=410)
    if error:
        lc._complete_cli(session_id, 0, error)
        return HTMLResponse(_FAILURE_PAGE.format(error=error))
    try:
        provider_id = await lc.ensure_provider(db, session["platform_id"], session["provider_id"])
        if session["flow"] == "cli-cline":
            key = await lc.complete_cline_code(provider_id, code, session.get("redirect_uri", ""), db)
        elif session["flow"] == "cli-google":
            key = await lc.complete_antigravity_code(provider_id, code, session["client_id"],
                                                     session["client_secret"], session.get("redirect_uri", ""), db)
        else:
            raise ValueError("unknown flow")
    except Exception as e:
        lc._complete_cli(session_id, 0, str(e)[:200])
        return HTMLResponse(_FAILURE_PAGE.format(error=str(e)[:200]))
    lc._complete_cli(session_id, key.id)
    return HTMLResponse(_SUCCESS_PAGE)


@router.get("/status/{session_id}")
async def cli_status(session_id: str, db: AsyncSession = Depends(get_db)):
    from app.services import local_cli as lc
    session = lc.get_cli_session(session_id)
    if not session:
        return {"status": "expired"}
    if session["flow"] == "cli-aws-device" and session["status"] == "pending":
        result = await lc.poll_amazonq_session(session_id, db)
        result.setdefault("user_code", session.get("user_code", ""))
        result.setdefault("verification_uri", session.get("verification_uri", ""))
        return result
    return {"status": session["status"], "key_id": session["key_id"], "error": session["error"]}
