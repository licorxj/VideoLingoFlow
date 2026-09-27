"""OAuth 2.0 (Authorization Code + PKCE) browser login, OmniRoute-style.

Flow for clients that cannot embed static keys:
  1. GET  /oauth/authorize  -> browser login page
  2. POST /oauth/authorize  -> credentials checked, authorization code issued
                               (redirected back as ?code=..&state=..)
  3. POST /oauth/token      -> code (+ code_verifier) exchanged for a JWT
                               access token usable as `Authorization: Bearer`

A plain JSON login exists at POST /api/auth/login for curl-style clients, and
POST /api/auth/credentials manages the admin username/password.
"""
import html
import secrets
import time
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.services import browser_auth

router = APIRouter(tags=["oauth"])

# Single-use authorization codes: code -> {client_id, redirect_uri, challenge, method, expires}
_auth_codes: dict[str, dict] = {}
CODE_TTL_SECONDS = 600

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


# ---------------------------------------------------------------- credentials

class CredentialsIn(BaseModel):
    username: str = "admin"
    password: str

class LoginIn(BaseModel):
    username: str = "admin"
    password: str


@router.get("/api/auth/status")
async def auth_status():
    username, configured = browser_auth._get_admin_credentials()
    return {"configured": bool(configured), "username": username if configured else ""}


@router.post("/api/auth/credentials")
async def set_credentials(data: CredentialsIn):
    if len(data.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")
    browser_auth.set_admin_credentials(data.username, data.password)
    return {"ok": True}


@router.post("/api/auth/login")
async def api_login(data: LoginIn):
    if not browser_auth.verify_admin_login(data.username, data.password):
        raise HTTPException(401, "Invalid username or password")
    token, ttl = browser_auth.mint_access_token(data.username)
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl}


# ---------------------------------------------------------------- oauth pages

_PAGE_STYLE = """
  body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
       background:#0b1220;font-family:system-ui,'Segoe UI',sans-serif;color:#e2e8f0}
  .card{width:320px;padding:32px;border-radius:14px;background:#111a2e;
        box-shadow:0 8px 30px rgba(0,0,0,.4)}
  h2{margin:0 0 4px;font-size:20px} p{margin:0 0 18px;font-size:12px;color:#7d8db1}
  input{width:100%;box-sizing:border-box;margin-bottom:12px;padding:10px 12px;border-radius:8px;
        border:1px solid #27354f;background:#0b1220;color:#e2e8f0;font-size:14px}
  button{width:100%;padding:10px;border:0;border-radius:8px;background:#0ea5e9;
         color:#fff;font-size:14px;font-weight:600;cursor:pointer}
  .err{background:#3b1220;border:1px solid #7f1d1d;color:#fca5a5;padding:8px 10px;
       border-radius:8px;font-size:12px;margin-bottom:12px}
"""


def _page(action: str, fields: dict, error: str = "") -> str:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in fields.items()
    )
    err = f'<div class="err">{html.escape(error)}</div>' if error else ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>LocalRouter 登录</title><style>{_PAGE_STYLE}</style></head><body>
<div class="card"><h2>LocalRouter</h2><p>浏览器登录授权 · Browser Login</p>
{err}
<form method="post" action="{html.escape(action)}">
{hidden}
<input name="username" placeholder="用户名 / Username" autocomplete="username" autofocus>
<input name="password" type="password" placeholder="密码 / Password" autocomplete="current-password">
<button type="submit">登录并授权</button>
</form></div></body></html>"""


def _error_page(message: str) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>LocalRouter</title><style>{_PAGE_STYLE}</style></head><body>
<div class="card"><h2>授权失败</h2><p>{html.escape(message)}</p></div></body></html>"""


def _validate_redirect_uri(redirect_uri: str) -> bool:
    try:
        parsed = urlparse(redirect_uri)
        return parsed.scheme in ("http", "https") and (
            parsed.hostname in _LOOPBACK_HOSTS or (parsed.hostname or "").endswith(".localhost")
        )
    except Exception:
        return False


def _pop_expired_codes():
    now = time.time()
    for k in [k for k, v in _auth_codes.items() if v["expires"] < now]:
        _auth_codes.pop(k, None)


@router.get("/oauth/authorize")
async def authorize_page(
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
):
    _pop_expired_codes()
    if response_type != "code":
        return HTMLResponse(_error_page("response_type must be 'code'"), status_code=400)
    if not redirect_uri or not _validate_redirect_uri(redirect_uri):
        return HTMLResponse(_error_page("redirect_uri 必须是本机回环地址（localhost / 127.0.0.1）"), status_code=400)
    if code_challenge_method and code_challenge_method not in ("S256", "plain"):
        return HTMLResponse(_error_page("code_challenge_method 仅支持 S256 / plain"), status_code=400)
    if not browser_auth.is_login_configured():
        return HTMLResponse(_error_page("尚未设置登录密码，请在 系统设置 → 端点设置 中配置"), status_code=400)

    fields = {
        "client_id": client_id, "redirect_uri": redirect_uri, "state": state,
        "code_challenge": code_challenge, "code_challenge_method": code_challenge_method or ("S256" if code_challenge else ""),
    }
    return HTMLResponse(_page("/oauth/authorize", fields))


@router.post("/oauth/authorize")
async def authorize_submit(request: Request):
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))
    state = str(form.get("state", ""))
    challenge = str(form.get("code_challenge", ""))
    method = str(form.get("code_challenge_method", ""))

    if not redirect_uri or not _validate_redirect_uri(redirect_uri):
        return HTMLResponse(_error_page("redirect_uri 无效"), status_code=400)
    if not browser_auth.is_login_configured():
        return HTMLResponse(_error_page("尚未设置登录密码，请在系统设置中配置"), status_code=400)

    if not browser_auth.verify_admin_login(username, password):
        fields = {k: str(form.get(k, "")) for k in ("client_id", "redirect_uri", "state", "code_challenge", "code_challenge_method")}
        return HTMLResponse(_page("/oauth/authorize", fields, error="用户名或密码错误 / Invalid credentials"), status_code=200)

    code = secrets.token_urlsafe(32)
    _auth_codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "challenge": challenge,
        "method": method or ("S256" if challenge else ""),
        "expires": time.time() + CODE_TTL_SECONDS,
    }
    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


@router.post("/oauth/token")
async def oauth_token(request: Request):
    _pop_expired_codes()
    if "application/json" in request.headers.get("content-type", ""):
        body = await request.json()
    else:
        body = dict(await request.form())

    if body.get("grant_type") != "authorization_code":
        raise HTTPException(400, {"error": "unsupported_grant_type"})
    code = str(body.get("code", ""))
    record = _auth_codes.pop(code, None)  # single use
    if not record:
        raise HTTPException(400, {"error": "invalid_grant", "error_description": "code is invalid or expired"})
    if record["redirect_uri"] != str(body.get("redirect_uri", "")):
        raise HTTPException(400, {"error": "invalid_grant", "error_description": "redirect_uri mismatch"})

    verifier = str(body.get("code_verifier", ""))
    if record["challenge"]:
        if record["method"] == "S256":
            import hashlib
            calc = browser_auth._b64url(hashlib.sha256(verifier.encode()).digest())
            ok = hmac_compare(calc, record["challenge"])
        else:  # plain
            ok = verifier == record["challenge"]
        if not ok:
            raise HTTPException(400, {"error": "invalid_grant", "error_description": "PKCE verification failed"})

    token, ttl = browser_auth.mint_access_token("admin")
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl}


def hmac_compare(a: str, b: str) -> bool:
    import hmac as _hmac
    return _hmac.compare_digest(a, b)
