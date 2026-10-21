"""Local CLI credential import: detect / paste / import for CLI-managed platforms."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_key import ApiKey
from app.models.model import Model
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
    server_url: str = ""           # opencode: 本地 opencode serve 地址（覆盖默认 127.0.0.1:10001）


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
            platform_cfg = local_cli.CLI_PLATFORMS.get(data.platform, {})
            if platform_cfg.get("no_credential_ok"):
                credential = {}  # opencode 等：服务端可无密码
            else:
                raise HTTPException(400, "No credential provided (token or refresh_token)")

    # Resolve or auto-create the provider (deduped by auth_type)
    if data.platform in local_cli.WORKBUDDY_REGION_BY_PLATFORM:
        # WorkBuddy 按条目固定区域（cn / intl），避免刷新或调用时走错站点
        credential["region"] = (data.region or local_cli.WORKBUDDY_REGION_BY_PLATFORM[data.platform]).strip()

    provider_id = await local_cli.ensure_provider(db, data.platform, data.provider_id)
    provider = await db.get(Provider, provider_id)
    # opencode：允许用导入时填写的本地服务端地址覆盖默认
    if data.server_url and data.platform == "opencode":
        provider.base_url = data.server_url.strip().rstrip("/")
        await db.commit()

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
    region: str = ""         # workbuddy: cn / intl(gl)


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
        if data.platform in lc.WORKBUDDY_REGION_BY_PLATFORM:
            return await lc.start_workbuddy_session(data.provider_id, data.platform)
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
    if session["flow"] == "cli-workbuddy" and session["status"] == "pending":
        result = await lc.poll_workbuddy_session(session_id, db)
        result.setdefault("authorize_url", session.get("authorize_url", ""))
        return result
    return {"status": session["status"], "key_id": session["key_id"], "error": session["error"]}


# ---------------------------------------------------------------- WorkBuddy

class WorkBuddyModelsRequest(BaseModel):
    provider_id: int = 0     # 0 => 自动定位 workbuddy provider
    key_id: int = 0          # 指定凭据；0 => 取该 provider 第一把 active key
    region: str = ""         # 留空则用凭据里保存的区域
    sync: bool = False       # True => 写入/更新 Model 表


async def _resolve_workbuddy_credential(data: "WorkBuddyModelsRequest", db: AsyncSession):
    """返回 (provider, api_key, region, credential)。"""
    from app.services import workbuddy
    from sqlalchemy import select

    provider = None
    if data.provider_id:
        provider = await db.get(Provider, data.provider_id)
    else:
        result = await db.execute(
            select(Provider).where(Provider.auth_type.in_(["workbuddy", "workbuddy-intl"])).order_by(Provider.id)
        )
        provider = result.scalars().first()
    if not provider:
        raise HTTPException(404, "未找到 WorkBuddy 供应商，请先完成 CLI 导入")

    if data.key_id:
        api_key = await db.get(ApiKey, data.key_id)
    else:
        result = await db.execute(
            select(ApiKey).where(ApiKey.provider_id == provider.id, ApiKey.status == "active").limit(1)
        )
        api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(400, "该供应商没有可用凭据，请先导入 WorkBuddy 账号")

    from app.services.oauth_providers import ensure_fresh_token
    await ensure_fresh_token(db, api_key)
    credential = workbuddy.load_credential(api_key)
    region = data.region or workbuddy.resolve_region(credential, provider.base_url or "")
    return provider, api_key, region, credential


@router.post("/workbuddy/models")
async def workbuddy_models(data: WorkBuddyModelsRequest, db: AsyncSession = Depends(get_db)):
    """拉取 WorkBuddy 官方模型目录（/v3/config），sync=true 时同步进 Model 表。"""
    from app.services import workbuddy

    provider, api_key, region, credential = await _resolve_workbuddy_credential(data, db)
    try:
        items = await workbuddy.list_models(region, credential)
    except Exception as e:
        raise HTTPException(502, f"WorkBuddy 模型目录拉取失败: {str(e)[:300]}")

    synced = 0
    if data.sync:
        synced = await _upsert_models(db, provider.id, items)
    return {
        "provider_id": provider.id,
        "region": region,
        "account": credential.get("nickname") or credential.get("uid") or "",
        "models": items,
        "synced": synced,
    }


async def _upsert_models(db: AsyncSession, provider_id: int, items: list[dict]) -> int:
    """按 model_id 幂等写入 Model 表。"""
    from sqlalchemy import select as _select

    existing_result = await db.execute(_select(Model).where(Model.provider_id == provider_id))
    existing = {m.model_id: m for m in existing_result.scalars().all()}
    touched = 0
    for item in items:
        model_id = item["model_id"]
        target = existing.get(model_id)
        if target is None:
            target = Model(
                provider_id=provider_id,
                model_id=model_id,
                display_name=item.get("display_name") or model_id,
                is_multimodal=bool(item.get("is_multimodal")),
                model_type="text",
                context_window=item.get("context_window"),
            )
            db.add(target)
        else:
            if item.get("display_name"):
                target.display_name = item["display_name"]
            if item.get("is_multimodal"):
                target.is_multimodal = True
            if item.get("context_window"):
                target.context_window = item["context_window"]
        touched += 1
    if touched:
        await db.commit()
    return touched
