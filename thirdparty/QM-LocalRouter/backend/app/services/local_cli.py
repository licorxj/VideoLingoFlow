"""Local CLI credential import (OmniRoute-style).

For platforms whose credentials live in a locally installed CLI/IDE, we import
the stored token (auto-detect on this machine or paste manually), store it as a
regular encrypted ApiKey, and refresh it through the platform's refresh
endpoint. Upstream calling per platform is described by `upstream`, consumed by
the forwarder.
"""
import glob
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings as app_settings
from app.models.api_key import ApiKey
from app.models.provider import Provider
from app.utils.crypto import encrypt_value, decrypt_value

HOME = os.path.expanduser("~")

CLI_PLATFORMS: dict[str, dict] = {
    "cline": {
        "label": "Cline / ClinePass",
        "flow": "local_cli",
        "import_modes": ["detect", "paste"],
        "detect_paths": [
            ("~/.cline/config.json", "json", "cline CLI"),
            ("~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json", "scan", "Cline VS Code"),
            (os.path.join(os.environ.get("APPDATA", ""), "Code", "User", "globalStorage", "saoudrizwan.claude-dev", "settings", "cline_mcp_settings.json") if os.environ.get("APPDATA") else "", "scan", "Cline VS Code"),
        ],
        "token_fields": ["access_token", "refresh_token"],
        "refresh": {"url": "https://api.cline.bot/api/v1/auth/refresh", "style": "json", "field": "refreshToken"},
        "upstream": {
            "api_base": "https://api.cline.bot",
            "auth": "bearer-workos",  # Cline rejects plain Bearer; token must be prefixed with workos:
            "extra_headers": {"Referer": "https://app.cline.bot/", "X-Title": "LocalRouter"},
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["cline", "api.cline.bot"],
    },
    "trae": {
        "label": "Trae (SOLO)",
        "flow": "local_cli",
        "import_modes": ["paste"],
        "token_lifetime_days": 14,
        "refresh": None,
        "upstream": {
            "api_base": "https://api.trae.ai",
            "chat_path": "/v1/chat/completions",
            "auth": "cloud-ide-jwt",
            "extra_headers": {"X-Trae-Client-Type": "web", "Referer": "https://solo.trae.ai/"},
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["trae", "core-normal.trae.ai"],
    },
    "opencode": {
        "label": "OpenCode Free",
        "flow": "local_cli",
        "import_modes": ["add", "detect", "paste"],
        "detect_paths": [
            ("~/.local/share/opencode/auth.json", "opencode_auth", "OpenCode CLI"),
            (os.path.join(os.environ.get("USERPROFILE", ""), ".local", "share", "opencode", "auth.json") if os.environ.get("USERPROFILE") else "", "opencode_auth", "OpenCode CLI"),
        ],
        "no_credential_ok": True,  # public free endpoint: no token required
        "refresh": None,
        "upstream": {
            "api_base": "https://opencode.ai/zen/v1",
            "chat_path": "/chat/completions",
            "auth": "bearer",  # free endpoint works without a key; a Zen key raises limits
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["opencode"],
    },
    "amazon-q": {
        "label": "Amazon Q (Kiro 凭据导入)",
        "flow": "local_cli",
        "import_modes": ["detect", "paste"],
        "detect_paths": [
            ("~/.aws/sso/cache/*.json", "aws_sso", "AWS SSO / Kiro cache"),
        ],
        "token_fields": ["refresh_token", "client_id", "client_secret", "region"],
        "refresh": {"aws_sso_oidc": True, "endpoint": "https://oidc.us-east-1.amazonaws.com/token"},
        "upstream": {
            "api_base": "",
            "auth": "bearer",
            "protocols": ["openai", "custom"],
            "pending": "CodeWhisperer eventstream adapter",
        },
        "match_keywords": ["amazon", "amazonq", "aws"],
    },
    "antigravity": {
        "label": "Antigravity / AGY CLI (Google)",
        "flow": "local_cli",
        "import_modes": ["detect", "paste"],
        "detect_paths": [
            ("~/.antigravity/oauth_creds.json", "json", "Antigravity CLI"),
            ("~/.agy/oauth_creds.json", "json", "AGY CLI"),
            ("~/.config/antigravity/oauth_creds.json", "json", "Antigravity CLI (linux)"),
        ],
        "token_fields": ["refresh_token", "client_id", "client_secret"],
        "refresh": {
            "url": "https://oauth2.googleapis.com/token",
            "style": "form",
            "client_id": "1071006060591-tmhssin2h21lcre235vtolojh4g403ep",
            "client_secret_field": "client_secret",
        },
        "upstream": {
            "api_base": "",
            "auth": "bearer",
            "protocols": ["openai", "custom"],
            "pending": "Google Code Assist v1internal adapter",
        },
        "match_keywords": ["antigravity", "agy"],
    },
}


def load_cli_platforms() -> dict:
    return {k: v for k, v in CLI_PLATFORMS.items()}


def get_cli_platform(pid: str) -> dict | None:
    return CLI_PLATFORMS.get(pid)


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def detect_credentials(platform_id: str) -> list[dict]:
    """Scan known local CLI/IDE credential locations. Returns masked candidates."""
    platform = CLI_PLATFORMS.get(platform_id)
    if not platform:
        return []
    found = []
    seen_paths = set()
    for path_tpl, kind, source in platform.get("detect_paths", []):
        if not path_tpl:
            continue
        path = os.path.expanduser(path_tpl)
        matches = sorted(glob.glob(path)) if "*" in path else [path]
        for mp in matches:
            if not os.path.exists(mp):
                continue
            resolved = os.path.realpath(mp)
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            if kind == "json":
                data = _read_json(mp)
                if not isinstance(data, dict):
                    continue
                if data.get("refresh_token") or data.get("access_token"):
                    found.append({
                        "path": mp.replace(HOME, "~"),
                        "source": source,
                        "fields": sorted([k for k in data.keys() if "token" in k.lower() or k in ("client_id", "client_secret", "region")]),
                    })
            elif kind == "aws_sso":
                data = _read_json(mp)
                if isinstance(data, dict) and data.get("refreshToken"):
                    found.append({
                        "path": mp.replace(HOME, "~"),
                        "source": source,
                        "fields": sorted([k for k in data.keys() if k in ("refreshToken", "clientId", "clientSecret", "region", "startUrl")]),
                    })
            elif kind == "opencode_auth":
                data = _read_json(mp)
                entry = (data or {}).get("opencode") or {}
                if entry.get("key") or entry.get("api_key"):
                    found.append({
                        "path": mp.replace(HOME, "~"),
                        "source": source,
                        "fields": ["zen api key"],
                    })
            elif kind == "scan":
                data = _read_json(mp)
                if data:
                    found.append({"path": mp.replace(HOME, "~"), "source": source, "fields": ["manual review"]})
    return found


def extract_credentials(platform_id: str, path: str) -> dict:
    """Read the full credential payload from a detected local file."""
    platform = CLI_PLATFORMS.get(platform_id)
    if not platform:
        raise ValueError(f"Unknown platform: {platform_id}")
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        raise ValueError(f"File not found: {path}")
    data = _read_json(path) or {}
    out: dict = {}
    if platform_id == "opencode":
        entry = (data.get("opencode") or {})
        key = entry.get("key") or entry.get("api_key")
        if key:
            out["access_token"] = key
        return out
    for field in platform.get("token_fields", []):
        camel = "".join(w.capitalize() if i else w for i, w in enumerate(field.split("_")))
        if field in data:
            out[field] = data[field]
        elif camel in data:
            out[field] = data[camel]
    if not out:
        raise ValueError("No credential fields found in file")
    return out


async def refresh_cli_token(db: AsyncSession, api_key: ApiKey) -> None:
    """Refresh a CLI-imported credential via its platform endpoint. Commits on success."""
    platform = CLI_PLATFORMS.get(api_key.oauth_profile)
    if not platform:
        return
    refresh_cfg = platform.get("refresh")
    if not refresh_cfg:
        return  # static token (trae) or no auth (opencode)
    try:
        blob = json.loads(decrypt_value(api_key.oauth_refresh)) if api_key.oauth_refresh else {}
    except Exception:
        blob = {}

    if refresh_cfg.get("aws_sso_oidc"):
        # AWS SSO OIDC createToken with the imported client registration
        payload = {
            "clientId": blob.get("client_id", ""),
            "clientSecret": blob.get("client_secret", ""),
            "grantType": "refresh_token",
            "refreshToken": blob.get("refresh_token", ""),
        }
        if not payload["refreshToken"]:
            return
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.post(refresh_cfg["endpoint"], json=payload,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
        new_blob = {**blob, "refresh_token": data.get("refreshToken", blob.get("refresh_token", ""))}
        api_key.key_value = encrypt_value(data.get("accessToken", ""))
        api_key.oauth_refresh = encrypt_value(json.dumps(new_blob))
        api_key.oauth_expires_at = int(time.time() + data.get("expiresIn", 3600))
    else:
        url = refresh_cfg["url"]
        style = refresh_cfg.get("style", "json")
        if style == "form":
            form = {
                "grant_type": "refresh_token",
                "refresh_token": blob.get("refresh_token", ""),
                "client_id": refresh_cfg.get("client_id") or blob.get("client_id", ""),
            }
            secret_field = refresh_cfg.get("client_secret_field")
            if secret_field and (refresh_cfg.get(secret_field) or blob.get("client_secret")):
                form["client_secret"] = refresh_cfg.get(secret_field) or blob.get("client_secret", "")
            headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                resp = await client.post(url, data=form, headers=headers)
        else:
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                resp = await client.post(url, json={refresh_cfg.get("field", "refresh_token"): blob.get("refresh_token", "")},
                                         headers=headers)
        resp.raise_for_status()
        data = resp.json()
        api_key.key_value = encrypt_value(data.get("access_token", ""))
        if data.get("refresh_token"):
            new_blob = {**blob, "refresh_token": data["refresh_token"]}
            api_key.oauth_refresh = encrypt_value(json.dumps(new_blob))
        api_key.oauth_expires_at = int(time.time() + data.get("expires_in", 3600))
    api_key.status = "active"
    api_key.last_error = ""
    await db.commit()



# ---------------------------------------------------------------- browser flows
# Sessions for platforms where the credential can be obtained in the browser
# (OmniRoute-style): cline authorization-code (self-contained base64 token),
# amazon-q AWS SSO device flow, antigravity Google authorization code.

_cli_sessions: dict[str, dict] = {}


def _new_session(provider_id: int, platform_id: str, flow: str) -> tuple[str, dict]:
    session_id = secrets.token_urlsafe(24)
    session = {
        "provider_id": provider_id, "platform_id": platform_id, "flow": flow,
        "status": "pending", "key_id": None, "error": "",
        "created": time.time(),
    }
    _cli_sessions[session_id] = session
    return session_id, session


def get_cli_session(session_id: str) -> dict | None:
    session = _cli_sessions.get(session_id)
    if session and time.time() - session["created"] > 600:
        return None
    return session


def _complete_cli(session_id: str, key_id: int, error: str = ""):
    session = _cli_sessions.get(session_id)
    if session:
        session["status"] = "failed" if error else "success"
        session["key_id"] = None if error else key_id
        session["error"] = error


def start_cline_session(provider_id: int) -> dict:
    session_id, session = _new_session(provider_id, "cline", "cli-cline")
    redirect_uri = f"http://127.0.0.1:{app_settings.BACKEND_PORT}/api/cli/callback/{session_id}"
    session["redirect_uri"] = redirect_uri
    authorize_url = (
        "https://api.cline.bot/api/v1/auth/authorize?"
        + urlencode({"client_type": "extension", "callback_url": redirect_uri, "redirect_uri": redirect_uri})
    )
    return {"session_id": session_id, "flow": "cli-cline", "authorize_url": authorize_url,
            "redirect_uri": redirect_uri}


async def complete_cline_code(provider_id: int, code: str, redirect_uri: str, db: AsyncSession) -> ApiKey:
    """Cline embeds tokens as base64 JSON inside the auth code (with an API fallback)."""
    import base64 as _b64
    from urllib.parse import unquote
    base64 = code
    try:
        base64 = unquote(base64)
    except Exception:
        pass
    base64 = base64.strip()
    padding = 4 - (len(base64) % 4)
    if padding != 4:
        base64 += "=" * padding
    token_data = None
    try:
        decoded = _b64.b64decode(base64).decode("utf-8", errors="replace")
        json_str = decoded[: decoded.rfind("}") + 1]
        token_data = json.loads(json_str)
    except Exception:
        token_data = None
    if token_data and token_data.get("accessToken"):
        key = await store_cli_key(db, provider_id, "cline",
                                  {"access_token": token_data["accessToken"],
                                   "refresh_token": token_data.get("refreshToken", "")})
        expires_at = token_data.get("expiresAt")
        if expires_at:
            try:
                import datetime
                dt = datetime.datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                key.oauth_expires_at = int(dt.timestamp())
                await db.commit()
            except Exception:
                pass
        return key
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        resp = await client.post("https://api.cline.bot/api/v1/auth/token",
                                 json={"grant_type": "authorization_code", "code": code,
                                       "client_type": "extension", "redirect_uri": redirect_uri},
                                 headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    d = data.get("data") or data
    access = d.get("accessToken", "")
    if not access:
        raise ValueError("Cline token exchange returned no accessToken")
    return await store_cli_key(db, provider_id, "cline",
                               {"access_token": access, "refresh_token": d.get("refreshToken", "")})


def start_amazonq_session(provider_id: int) -> dict:
    session_id, session = _new_session(provider_id, "amazon-q", "cli-aws-device")
    base = "https://oidc.us-east-1.amazonaws.com"
    reg = httpx.post(f"{base}/client/register",
                     json={"clientName": "kiro-oauth-client", "clientType": "public",
                           "scopes": ["codewhisperer:completions", "codewhisperer:analysis", "codewhisperer:conversations"],
                           "grantTypes": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
                           "issuerUrl": "https://identitycenter.amazonaws.com/ssoins-722374e8c3c8e6c6"},
                     headers={"Accept": "application/json"}, timeout=30, trust_env=False)
    reg.raise_for_status()
    client_info = reg.json()
    dev = httpx.post(f"{base}/device_authorization",
                     json={"clientId": client_info["clientId"], "clientSecret": client_info["clientSecret"],
                           "startUrl": "https://view.awsapps.com/start"},
                     headers={"Accept": "application/json"}, timeout=30, trust_env=False)
    dev.raise_for_status()
    device = dev.json()
    session.update({
        "device_code": device.get("deviceCode", ""), "user_code": device.get("userCode", ""),
        "verification_uri": device.get("verificationUri", ""),
        "interval": int(device.get("interval") or 5), "last_poll": 0,
        "client_id": client_info["clientId"], "client_secret": client_info["clientSecret"],
        "region": "us-east-1", "token_url": f"{base}/token",
    })
    return {"session_id": session_id, "flow": "cli-aws-device", "user_code": session["user_code"],
            "verification_uri": session["verification_uri"],
            "authorize_url": device.get("verificationUriComplete") or session["verification_uri"]}


async def poll_amazonq_session(session_id: str, db: AsyncSession) -> dict:
    session = _cli_sessions.get(session_id)
    if not session or session["status"] != "pending":
        return {"status": session["status"] if session else "expired", "key_id": session.get("key_id") if session else None}
    now = time.time()
    if now - session.get("last_poll", 0) < session["interval"]:
        return {"status": "pending", "user_code": session["user_code"], "verification_uri": session["verification_uri"]}
    session["last_poll"] = now
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        resp = await client.post(session["token_url"], json={
            "clientId": session["client_id"], "clientSecret": session["client_secret"],
            "deviceCode": session["device_code"],
            "grantType": "urn:ietf:params:oauth:grant-type:device_code",
        }, headers={"Accept": "application/json"})
    try:
        data = resp.json()
    except Exception:
        data = {"error": "invalid_response"}
    if data.get("accessToken"):
        credential = {"access_token": data["accessToken"], "refresh_token": data.get("refreshToken", ""),
                      "client_id": session["client_id"], "client_secret": session["client_secret"],
                      "region": session["region"]}
        provider_id = await ensure_provider(db, "amazon-q", session["provider_id"])
        key = await store_cli_key(db, provider_id, "amazon-q", credential)
        _complete_cli(session_id, key.id)
        return {"status": "success", "key_id": key.id}
    err = data.get("error", "")
    if err in ("authorization_pending", "slow_down"):
        if err == "slow_down":
            session["interval"] += 5
        return {"status": "pending", "user_code": session["user_code"], "verification_uri": session["verification_uri"]}
    _complete_cli(session_id, 0, err or "device flow failed")
    return {"status": "failed", "error": err}


def start_antigravity_session(provider_id: int, client_id: str, client_secret: str) -> dict:
    if not client_id or not client_secret:
        raise ValueError("Antigravity browser login needs client_id/client_secret (detect or paste first)")
    session_id, session = _new_session(provider_id, "antigravity", "cli-google")
    redirect_uri = f"http://127.0.0.1:{app_settings.BACKEND_PORT}/api/cli/callback/{session_id}"
    session.update({"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri})
    params = {
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/cclog https://www.googleapis.com/auth/experimentsandconfigs",
        "access_type": "offline", "prompt": "consent", "state": session_id,
    }
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    session["authorize_url"] = authorize_url
    return {"session_id": session_id, "flow": "cli-google", "authorize_url": authorize_url, "redirect_uri": redirect_uri}


async def complete_antigravity_code(provider_id: int, code: str, client_id: str, client_secret: str,
                                    redirect_uri: str, db: AsyncSession) -> ApiKey:
    form = {"grant_type": "authorization_code", "code": code, "client_id": client_id,
            "client_secret": client_secret, "redirect_uri": redirect_uri}
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data=form,
                                 headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    credential = {"access_token": data.get("access_token", ""), "refresh_token": data.get("refresh_token", ""),
                  "client_id": client_id, "client_secret": client_secret}
    if not credential["access_token"]:
        raise ValueError("Google token exchange returned no access_token")
    return await store_cli_key(db, provider_id, "antigravity", credential)


async def ensure_provider(db: AsyncSession, platform_id: str, provider_id: int) -> int:
    """Return the provider id; reuse or auto-create the platform's CLI provider."""
    if provider_id:
        return provider_id
    platform = CLI_PLATFORMS.get(platform_id, {})
    upstream = platform.get("upstream") or {}
    existing = await db.execute(select(Provider).where(Provider.auth_type == platform_id).order_by(Provider.id))
    found = existing.scalars().first()
    if found:
        if not found.base_url and upstream.get("api_base"):
            found.base_url = upstream["api_base"]
            await db.commit()
        return found.id
    provider = Provider(
        name=f"{platform.get('label', platform_id)} (CLI)",
        protocol="openai",
        base_url=upstream.get("api_base", ""),
        auth_type=platform_id,
        description=f"Imported from local CLI ({platform_id})",
        icon="",
        homepage="",
        is_active=True,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider.id


def parse_code_from_paste(pasted: str) -> str:
    """Accept a raw code or a full callback URL; return the code."""
    pasted = (pasted or "").strip()
    if "code=" in pasted:
        from urllib.parse import urlparse, parse_qs
        try:
            q = parse_qs(urlparse(pasted).query)
            if q.get("code"):
                return q["code"][0]
        except Exception:
            pass
    return pasted



async def store_cli_key(db: AsyncSession, provider_id: int, platform_id: str, credential: dict) -> ApiKey:
    """Store imported CLI credentials as the provider's key (replaces previous)."""
    # normalize camelCase keys from AWS SSO files
    norm = {}
    mapping = {"refreshToken": "refresh_token", "clientId": "client_id", "clientSecret": "client_secret",
               "accessToken": "access_token", "region": "region", "startUrl": "start_url",
               "id_token": "id_token", "access_token": "access_token", "refresh_token": "refresh_token"}
    for k, v in credential.items():
        norm[mapping.get(k, k)] = v
    access = norm.get("access_token") or norm.get("refresh_token") or norm.get("id_token")
    if not access and platform_id == "opencode":
        access = "KEYLESS"  # free-tier models work without any Authorization header (OmniRoute #8467)
    if not access:
        raise ValueError("credential payload has no usable token")
    blob = {k: v for k, v in norm.items() if k != "access_token"}

    result = await db.execute(select(ApiKey).where(ApiKey.provider_id == provider_id, ApiKey.oauth_profile == platform_id))
    for old in result.scalars().all():
        await db.delete(old)
    expires_at = 0
    lifetime = CLI_PLATFORMS.get(platform_id, {}).get("token_lifetime_days")
    if lifetime:
        expires_at = int(time.time() + lifetime * 86400)
    key = ApiKey(
        provider_id=provider_id,
        key_value=encrypt_value(access),
        alias=f"CLI-{platform_id}",
        weight=1,
        status="active",
        oauth_profile=platform_id,
        oauth_refresh=encrypt_value(json.dumps(blob)) if blob else "",
        oauth_expires_at=expires_at,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key
