"""Browser-login (OAuth) credential helpers: password hashing + HS256 JWT.

Pure stdlib so no new dependencies: PBKDF2 for the admin password, HMAC-SHA256
compact JWTs for access tokens. The JWT secret is auto-generated once and
persisted in the settings file.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

from app.routers.settings import _get_settings, _save_settings

_PBKDF2_ITERS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(calc.hex(), digest)
    except Exception:
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _ensure_jwt_secret() -> str:
    settings = _get_settings()
    secret = settings.get("jwt_secret") or ""
    if not secret:
        secret = secrets.token_hex(32)
        settings["jwt_secret"] = secret
        _save_settings(settings)
    return secret


def _get_admin_credentials() -> tuple[str, str]:
    """(username, password_hash) — hash may be empty when not configured yet."""
    settings = _get_settings()
    return settings.get("admin_username", "admin"), settings.get("admin_password_hash", "")


def set_admin_credentials(username: str, password: str):
    settings = _get_settings()
    settings["admin_username"] = (username or "admin").strip() or "admin"
    settings["admin_password_hash"] = hash_password(password)
    _save_settings(settings)


def verify_admin_login(username: str, password: str) -> bool:
    stored_user, stored_hash = _get_admin_credentials()
    if not stored_hash:
        return False
    return hmac.compare_digest(username, stored_user) and verify_password(password, stored_hash)


def mint_access_token(username: str, ttl_hours: float | None = None) -> tuple[str, int]:
    settings = _get_settings()
    ttl_seconds = int((ttl_hours or settings.get("oauth_token_hours", 24)) * 3600)
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": username, "typ": "access", "iat": now, "exp": now + ttl_seconds}
    signing_input = _b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(_ensure_jwt_secret().encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64url(sig), ttl_seconds


def verify_access_token(token: str) -> dict | None:
    """Return the payload when the JWT signature and expiry are valid, else None."""
    try:
        head_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = head_b64 + "." + payload_b64
        expected = hmac.new(_ensure_jwt_secret().encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))):
            return None
        header = json.loads(base64.urlsafe_b64decode(head_b64 + "=" * (-len(head_b64) % 4)))
        if header.get("alg") != "HS256":
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
        if payload.get("typ") != "access" or payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def is_login_configured() -> bool:
    return _get_admin_credentials()[1] != ""
