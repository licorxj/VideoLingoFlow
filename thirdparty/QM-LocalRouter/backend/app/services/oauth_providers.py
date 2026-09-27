"""OAuth login support for providers that authenticate via browser (OmniRoute-style).

Handles the full browser authorization-code + PKCE flow:
  start  -> build authorize URL with our backend as the loopback redirect target
  callback -> exchange the code for access/refresh tokens, store them as an ApiKey
  refresh  -> silently rotate expired access tokens before forwarding

Provider profiles live in backend/data/oauth_profiles.json (user-editable).
"""
import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.models.api_key import ApiKey
from app.utils.crypto import encrypt_value, decrypt_value
from app.services import local_cli

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
PROFILES_PATH = os.path.join(DATA_DIR, "oauth_profiles.json")

DEFAULT_PROFILES = {
    "_README": "OAuth 平台配置（平台名单与端点对齐 OmniRoute Provider Reference v3.8.50）。"
               "flow: authorization_code | device | codebuddy(腾讯自定义设备码)。"
               "token_request_style: form(Anthropic/Auth0 要求 form-urlencoded) 或 json。"
               "requires_client_id=true 的平台需按官方 CLI 的公开凭据补填 client_id。"
               "upstream 定义转发时的默认 API 地址与鉴权头；exchange_url 表示拿到平台凭证后还需兑换真正的 API 令牌（如 Copilot）。",
    "claude": {
        "label": "Claude Code (Pro/Max 订阅)",
        "flow": "authorization_code",
        "authorize_url": "https://claude.ai/oauth/authorize",
        "token_url": "https://api.anthropic.com/v1/oauth/token",
        "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
        "scopes": "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers",
        "pkce": True,
        "token_request_style": "form",
        "refresh_headers": {"anthropic-beta": "oauth-2025-04-20"},
        "upstream": {
            "api_base": "https://api.anthropic.com",
            "auth": "bearer",
            "extra_headers": {"anthropic-beta": "oauth-2025-04-20"},
            "protocols": ["claude"],
        },
        "match_keywords": ["claude", "anthropic"],
    },
    "codex": {
        "label": "OpenAI Codex (ChatGPT 订阅)",
        "flow": "authorization_code",
        "authorize_url": "https://auth.openai.com/oauth/authorize",
        "token_url": "https://auth.openai.com/oauth/token",
        "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
        "scopes": "openid profile email offline_access",
        "pkce": True,
        "token_request_style": "form",
        "extra_params": {"id_token_add_organizations": "true", "codex_cli_simplified_flow": "true",
                         "originator": "codex_cli_rs", "prompt": "login"},
        "upstream": {
            "api_base": "https://chatgpt.com/backend-api/codex",
            "auth": "bearer",
            "upstream_style": "responses",
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["codex", "chatgpt", "backend-api/codex"],
    },
    "github-copilot": {
        "label": "GitHub Copilot",
        "flow": "device",
        "device_code_url": "https://github.com/login/device/code",
        "device_code_headers": {"Accept": "application/json"},
        "device_code_params": {"client_id": "Iv1.b507a08c87ecfe98", "scope": "read:user"},
        "token_url": "https://github.com/login/oauth/access_token",
        "token_headers": {"Accept": "application/json"},
        "token_params": {"client_id": "Iv1.b507a08c87ecfe98"},
        "device_grant": "urn:ietf:params:oauth:grant-type:device_code",
        "poll_interval": 5,
        # GitHub OAuth token -> short-lived Copilot API token
        "exchange_url": "https://api.github.com/copilot_internal/v2/token",
        "exchange_auth_style": "token",
        "exchange_token_field": "token",
        "expires_field": "expires_at",
        "upstream": {
            "api_base": "https://api.githubcopilot.com",
            "auth": "bearer",
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["copilot", "api.githubcopilot.com"],
    },
    "kimi-coding": {
        "label": "Kimi Code CLI (Kimi Coding Plan)",
        "flow": "device",
        "requires_client_id": True,
        "client_id": "",
        "device_code_url": "https://auth.kimi.com/api/oauth/device_authorization",
        "token_url": "https://auth.kimi.com/api/oauth/token",
        "token_request_style": "form",
        "device_grant": "urn:ietf:params:oauth:grant-type:device_code",
        "poll_interval": 5,
        "upstream": {
            "api_base": "https://api.kimi.com/coding",
            "auth": "bearer",
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["kimi", "api.kimi.com"],
    },
    "codebuddy-cn": {
        "label": "CodeBuddy CN (腾讯)",
        "flow": "codebuddy",
        "state_url": "https://copilot.tencent.com/v2/plugin/auth/state",
        "token_url": "https://copilot.tencent.com/v2/plugin/auth/token",
        "refresh_url": "https://copilot.tencent.com/v2/plugin/auth/token/refresh",
        "refresh_style": "header",
        "poll_interval": 5,
        "user_agent": "CLI/2.63.2 CodeBuddy/2.63.2",
        "upstream": {
            "api_base": "https://copilot.tencent.com",
            "auth": "bearer",
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["codebuddy", "copilot.tencent.com"],
    },
    "xai-oauth": {
        "label": "xAI OAuth (Grok)",
        "flow": "authorization_code",
        "requires_client_id": True,
        "client_id": "",
        "authorize_url": "https://auth.x.ai/oauth2/authorize",
        "token_url": "https://auth.x.ai/oauth2/token",
        "scopes": "openid profile email offline_access grok-cli:access api:access",
        "pkce": True,
        "token_request_style": "form",
        "upstream": {
            "api_base": "https://api.x.ai",
            "auth": "bearer",
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["x.ai", "grok", "xai"],
    },
    "openference": {
        "label": "Openference",
        "flow": "authorization_code",
        "requires_client_id": True,
        "client_id": "",
        "authorize_url": "https://openference.com/app/oauth/authorize",
        "token_url": "https://openference.com/oauth/token",
        "scopes": "openid profile email model:invoke offline_access",
        "pkce": True,
        "token_request_style": "form",
        "upstream": {
            "api_base": "https://api.openference.com",
            "auth": "bearer",
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["openference"],
    },
    "gitlab-duo": {
        "label": "GitLab Duo (需自建 OAuth 应用)",
        "flow": "authorization_code",
        "requires_client_id": True,
        "client_id": "",
        "authorize_url": "https://gitlab.com/oauth/authorize",
        "token_url": "https://gitlab.com/oauth/token",
        "scopes": "ai_features read_user",
        "pkce": True,
        "token_request_style": "form",
        "upstream": {
            "api_base": "https://gitlab.com",
            "auth": "bearer",
            "protocols": ["openai", "custom"],
        },
        "match_keywords": ["gitlab"],
    },
}


def load_profiles() -> dict:
    import json
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    profiles = {k: v for k, v in {**DEFAULT_PROFILES, **data}.items() if not k.startswith("_")}
    # keep a user-editable file present
    if not os.path.exists(PROFILES_PATH):
        save_profiles({**DEFAULT_PROFILES, **data})
    return profiles


def save_profiles(data: dict):
    import json
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_profile(profile_id: str) -> dict | None:
    return load_profiles().get(profile_id)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# ---------------------------------------------------------------- sessions

# session_id -> {provider_id, profile_id, verifier, redirect_uri, state,
#                status: pending|success|failed, key_id, error, expires}
_sessions: dict[str, dict] = {}
SESSION_TTL = 600


def _pop_expired_sessions():
    now = time.time()
    for k in [k for k, v in _sessions.items() if v["expires"] < now]:
        _sessions.pop(k, None)


def start_session(provider_id: int, profile_id: str) -> dict:
    profile = get_profile(profile_id)
    if not profile:
        raise ValueError(f"Unknown OAuth profile: {profile_id}")
    _pop_expired_sessions()
    session_id = secrets.token_urlsafe(24)

    if profile.get("flow") == "device":
        return _start_device_session(provider_id, profile_id, profile, session_id)
    if profile.get("flow") == "codebuddy":
        return _start_codebuddy_session(provider_id, profile_id, profile, session_id)

    if profile.get("requires_client_id") and not profile.get("client_id"):
        raise ValueError(f"Platform '{profile_id}' needs its public client_id filled in oauth_profiles.json first")
    verifier = secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest()) if profile.get("pkce") else ""
    redirect_uri = f"http://127.0.0.1:{app_settings.BACKEND_PORT}/api/oauth/callback/{session_id}"
    params = {
        "response_type": "code",
        "client_id": profile["client_id"],
        "redirect_uri": redirect_uri,
        "state": session_id,
    }
    if profile.get("scopes"):
        params["scope"] = profile["scopes"]
    for k, v in (profile.get("extra_params") or {}).items():
        params[k] = v
    if challenge:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    authorize_url = f"{profile['authorize_url']}?{urlencode(params)}"
    _sessions[session_id] = {
        "provider_id": provider_id,
        "profile_id": profile_id,
        "flow": "authorization_code",
        "verifier": verifier,
        "redirect_uri": redirect_uri,
        "state": session_id,
        "status": "pending",
        "key_id": None,
        "error": "",
        "expires": time.time() + SESSION_TTL,
    }
    return {"session_id": session_id, "flow": "authorization_code", "authorize_url": authorize_url}


def _start_device_session(provider_id: int, profile_id: str, profile: dict, session_id: str) -> dict:
    """GitHub-style device flow: request a device+user code, the user approves in browser."""
    if profile.get("requires_client_id") and not profile.get("client_id"):
        raise ValueError(f"Platform '{profile_id}' needs its public client_id filled in oauth_profiles.json first")
    device_params = dict(profile.get("device_code_params") or {"client_id": profile.get("client_id", "")})
    if not device_params.get("client_id") and profile.get("client_id"):
        device_params["client_id"] = profile["client_id"]
    resp = httpx.post(
        profile["device_code_url"],
        data=device_params,
        headers=profile.get("device_code_headers", {"Accept": "application/json"}),
        timeout=30, trust_env=False,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise ValueError(f"Device flow start failed: {data['error']}")
    _sessions[session_id] = {
        "provider_id": provider_id,
        "profile_id": profile_id,
        "flow": "device",
        "device_code": data.get("device_code", ""),
        "user_code": data.get("user_code", ""),
        "verification_uri": data.get("verification_uri", profile.get("verification_uri", "")),
        "interval": int(data.get("interval") or profile.get("poll_interval", 5)),
        "last_poll": 0,
        "status": "pending",
        "key_id": None,
        "error": "",
        "expires": time.time() + SESSION_TTL,
    }
    return {
        "session_id": session_id,
        "flow": "device",
        "user_code": data.get("user_code", ""),
        "verification_uri": data.get("verification_uri", ""),
        "authorize_url": data.get("verification_uri", ""),
    }


async def poll_device_session(session_id: str, db: AsyncSession) -> dict:
    """One non-blocking poll step of a device-flow session."""
    session = _sessions.get(session_id)
    if not session or session.get("flow") not in ("device", "codebuddy"):
        return {"status": "expired"}
    if session["status"] != "pending":
        return {"status": session["status"], "key_id": session["key_id"], "error": session["error"]}

    now = time.time()
    if now - session["last_poll"] < session["interval"]:
        return {"status": "pending", "user_code": session["user_code"], "verification_uri": session["verification_uri"]}
    session["last_poll"] = now

    profile = get_profile(session["profile_id"])
    if profile.get("flow") == "codebuddy":
        return await _poll_codebuddy_session(profile, session, db, session_id)
    try:
        token_data = {
            **profile.get("token_params", {"client_id": profile.get("client_id", "")}),
            "device_code": session["device_code"],
            "grant_type": profile.get("device_grant", "urn:ietf:params:oauth:grant-type:device_code"),
        }
        headers = dict(profile.get("token_headers", {"Accept": "application/json"}))
        if profile.get("token_request_style") == "json":
            resp = httpx.post(profile["token_url"], json=token_data, headers=headers, timeout=30, trust_env=False)
        else:
            resp = httpx.post(profile["token_url"], data=token_data, headers=headers, timeout=30, trust_env=False)
        data = resp.json()
    except Exception as e:
        return {"status": "pending", "user_code": session["user_code"], "verification_uri": session["verification_uri"], "transport_error": str(e)[:100]}

    if data.get("access_token"):
        try:
            tokens = await _maybe_exchange(profile, data["access_token"])
            key = await store_oauth_key(db, session["provider_id"], session["profile_id"], tokens)
            complete_session(session_id, key.id)
            return {"status": "success", "key_id": key.id}
        except Exception as e:
            fail_session(session_id, str(e)[:200])
            return {"status": "failed", "error": str(e)[:200]}
    err = data.get("error", "")
    if err in ("authorization_pending", "slow_down"):
        if err == "slow_down":
            session["interval"] = session["interval"] + 5
        return {"status": "pending", "user_code": session["user_code"], "verification_uri": session["verification_uri"]}
    fail_session(session_id, err or "device flow failed")
    return {"status": "failed", "error": err}


async def _maybe_exchange(profile: dict, credential_token: str) -> dict:
    """Run the optional second-stage exchange (e.g. GitHub token -> Copilot token)."""
    if not profile.get("exchange_url"):
        return {"access_token": credential_token}
    headers = {"Accept": "application/json"}
    if profile.get("exchange_auth_style") == "token":
        headers["Authorization"] = f"token {credential_token}"
    else:
        headers["Authorization"] = f"Bearer {credential_token}"
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        resp = await client.get(profile["exchange_url"], headers=headers)
        resp.raise_for_status()
        data = resp.json()
    token = data.get(profile.get("exchange_token_field", "token"), "")
    if not token:
        raise ValueError(f"Exchange returned no '{profile.get('exchange_token_field', 'token')}' field")
    return {
        "access_token": token,
        "refresh_token": credential_token,  # keep the primary credential for re-exchange
        "expires_at": data.get(profile.get("expires_field", ""), 0),
    }


def get_session(session_id: str) -> dict | None:
    return _sessions.get(session_id)


async def exchange_code(profile: dict, code: str, session: dict) -> dict:
    """Exchange an authorization code for tokens (test-overridable)."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": profile["client_id"],
        "redirect_uri": session["redirect_uri"],
    }
    if session.get("verifier") and profile.get("pkce"):
        data["code_verifier"] = session["verifier"]
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        resp = await client.post(profile["token_url"], json=data,
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


async def refresh_token(profile: dict, refresh_token_value: str) -> dict:
    """Refresh via the profile's token/refresh endpoint.

    Styles: "form" (Anthropic/Auth0 require x-www-form-urlencoded; Codex must NOT
    send scope — RFC 6749 §6), "json", "header" (CodeBuddy: refresh token rides in
    X-Refresh-Token header, response is {code:0,data:{accessToken,...}}).
    """
    style = profile.get("refresh_style") or ("json" if profile.get("token_request_style") == "json" else "form")
    url = profile.get("refresh_url") or profile["token_url"]

    if style == "header":
        headers = {
            "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": profile.get("user_agent", "CodeBuddy CLI"),
            "X-Requested-With": "XMLHttpRequest", "X-Domain": "copilot.tencent.com",
            "X-Refresh-Token": refresh_token_value, "X-Auth-Refresh-Source": "plugin",
            "X-Product": "SaaS",
        }
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.post(url, json={}, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0 or not (data.get("data") or {}).get("accessToken"):
            raise ValueError(f"Refresh returned no token: {str(data.get('msg') or data.get('code'))[:100]}")
        d = data["data"]
        return {"access_token": d["accessToken"], "refresh_token": d.get("refreshToken", refresh_token_value),
                "expires_in": d.get("expiresIn", 3600)}

    if style == "form":
        # form-urlencoded per OAuth2 spec; extra refresh headers (e.g. anthropic-beta) apply
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        headers.update(profile.get("refresh_headers") or {})
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_value,
            "client_id": profile.get("client_id", ""),
        }
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.post(url, data=data, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        resp = await client.post(url, json={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_value,
            "client_id": profile.get("client_id", ""),
        }, headers={"Content-Type": "application/json", "Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


def complete_session(session_id: str, key_id: int):
    session = _sessions.get(session_id)
    if session:
        session["status"] = "success"
        session["key_id"] = key_id


def fail_session(session_id: str, error: str):
    session = _sessions.get(session_id)
    if session:
        session["status"] = "failed"
        session["error"] = error


def _start_codebuddy_session(provider_id: int, profile_id: str, profile: dict, session_id: str) -> dict:
    """Tencent CodeBuddy custom device flow: POST state -> open authUrl -> GET poll?state="""
    ua = profile.get("user_agent", "CodeBuddy CLI")
    headers = {
        "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": ua, "X-Requested-With": "XMLHttpRequest",
        "X-Domain": "copilot.tencent.com", "X-Product": "SaaS",
    }
    resp = httpx.post(
        f'{profile["state_url"]}?platform=CLI', json={}, headers=headers, timeout=30, trust_env=False,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0 or not (data.get("data") or {}).get("state"):
        raise ValueError(f"CodeBuddy state error: {data.get('msg') or 'no state in response'}")
    state = str(data["data"]["state"])
    auth_url = str(data["data"].get("authUrl") or data["data"].get("url") or "")
    _sessions[session_id] = {
        "provider_id": provider_id,
        "profile_id": profile_id,
        "flow": "codebuddy",
        "device_code": state,
        "user_code": state,
        "verification_uri": auth_url,
        "interval": max(1, int(profile.get("poll_interval", 5))),
        "last_poll": 0,
        "status": "pending",
        "key_id": None,
        "error": "",
        "expires": time.time() + SESSION_TTL,
    }
    return {"session_id": session_id, "flow": "codebuddy", "user_code": state,
            "verification_uri": auth_url, "authorize_url": auth_url}


async def _poll_codebuddy_session(profile: dict, session: dict, db: AsyncSession, session_id: str) -> dict:
    """Poll the CodeBuddy token endpoint: GET tokenUrl?state=<state> (code 11217 = pending)."""
    ua = profile.get("user_agent", "CodeBuddy CLI")
    headers = {
        "Accept": "application/json", "User-Agent": ua,
        "X-Requested-With": "XMLHttpRequest", "X-Domain": "copilot.tencent.com", "X-Product": "SaaS",
    }
    try:
        resp = httpx.get(
            f'{profile["token_url"]}?state={session["device_code"]}',
            headers=headers, timeout=30, trust_env=False,
        )
        data = resp.json()
    except Exception as e:
        return {"status": "pending", "user_code": session["user_code"], "verification_uri": session["verification_uri"], "transport_error": str(e)[:100]}
    if data.get("code") == 0 and (data.get("data") or {}).get("accessToken"):
        tokens = {
            "access_token": data["data"]["accessToken"],
            "refresh_token": data["data"].get("refreshToken", ""),
            "expires_in": data["data"].get("expiresIn", 3600),
        }
        try:
            key = await store_oauth_key(db, session["provider_id"], session["profile_id"], tokens)
            complete_session(session_id, key.id)
            return {"status": "success", "key_id": key.id}
        except Exception as e:
            fail_session(session_id, str(e)[:200])
            return {"status": "failed", "error": str(e)[:200]}
    if data.get("code") == 11217:  # pending per official CLI
        return {"status": "pending", "user_code": session["user_code"], "verification_uri": session["verification_uri"]}
    msg = str(data.get("msg") or data.get("code") or "codebuddy flow failed")
    fail_session(session_id, msg)
    return {"status": "failed", "error": msg}


async def store_oauth_key(db: AsyncSession, provider_id: int, profile_id: str, tokens: dict) -> ApiKey:
    """Persist the OAuth access token as this provider's ApiKey."""
    access = tokens.get("access_token", "")
    if not access:
        raise ValueError("token endpoint returned no access_token")
    # Replace the previous OAuth key of this provider (one login = one active token)
    existing = await db.execute(
        select(ApiKey).where(ApiKey.provider_id == provider_id, ApiKey.oauth_profile == profile_id)
    )
    for old in existing.scalars().all():
        await db.delete(old)
    expires_at = int(tokens.get("expires_at") or (time.time() + tokens.get("expires_in", 3600)))
    key = ApiKey(
        provider_id=provider_id,
        key_value=encrypt_value(access),
        alias=f"OAuth-{profile_id}",
        weight=1,
        status="active",
        oauth_profile=profile_id,
        oauth_refresh=encrypt_value(tokens.get("refresh_token", "")) if tokens.get("refresh_token") else "",
        oauth_expires_at=expires_at,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


async def ensure_fresh_token(db: AsyncSession, api_key: ApiKey, force: bool = False) -> None:
    """Refresh the access token when it is about to expire. Commits on success."""
    if not api_key.oauth_profile:
        return
    if api_key.oauth_profile in local_cli.CLI_PLATFORMS:
        from app.services.local_cli import refresh_cli_token
        await refresh_cli_token(db, api_key)
        return
    if not api_key.oauth_refresh:
        return
    if not force and api_key.oauth_expires_at and api_key.oauth_expires_at > time.time() + 120:
        return
    profile = get_profile(api_key.oauth_profile)
    if not profile:
        return
    try:
        credential = decrypt_value(api_key.oauth_refresh)
        if profile.get("exchange_url"):
            # Exchange-style platforms (e.g. Copilot): mint a fresh gateway token
            tokens = await _maybe_exchange(profile, credential)
            api_key.key_value = encrypt_value(tokens["access_token"])
            api_key.oauth_expires_at = int(tokens.get("expires_at") or (time.time() + tokens.get("expires_in", 3600)))
        else:
            tokens = await refresh_token(profile, credential)
            api_key.key_value = encrypt_value(tokens["access_token"])
            if tokens.get("refresh_token"):
                api_key.oauth_refresh = encrypt_value(tokens["refresh_token"])
            api_key.oauth_expires_at = int(tokens.get("expires_at") or (time.time() + tokens.get("expires_in", 3600)))
        api_key.status = "active"
        api_key.last_error = ""
        await db.commit()
    except Exception as e:
        api_key.last_error = f"OAuth refresh failed: {str(e)[:200]}"
        await db.commit()
