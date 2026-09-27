"""Online provider discovery, modeled after OmniRoute.

Source: models.dev open database (https://models.dev/api.json) — the same
catalog OmniRoute syncs its provider list from. Icons use lobe-icons static
PNGs (https://github.com/lobehub/lobe-icons), the same logo set OmniRoute
renders in its dashboard.
"""
import json
import os
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/providers", tags=["online-providers"])

MODELS_DEV_URL = "https://models.dev/api.json"
CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "online_providers.json"
)

# models.dev omits "api" for first-party providers (their official SDK endpoints
# are assumed). These are the official OpenAI-compatible / native base URLs.
_WELL_KNOWN_API = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com/v1beta",
    "google-vertex": "https://aiplatform.googleapis.com",
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "deepinfra": "https://api.deepinfra.com/v1/openai",
    "mistral": "https://api.mistral.ai/v1",
    "xai": "https://api.x.ai/v1",
    "cohere": "https://api.cohere.ai/compatibility/v1",
    "togetherai": "https://api.together.xyz/v1",
    "perplexity": "https://api.perplexity.ai",
}


def _icon_url(provider_id: str) -> str:
    return f"https://unpkg.com/@lobehub/icons-static-png@latest/light/{provider_id}.png"


def _npm_to_protocol(npm: str) -> str:
    # models.dev tags each provider with its ai-sdk package; that reveals the wire protocol
    if "anthropic" in npm:
        return "claude"
    if npm.startswith("@ai-sdk/google"):
        return "gemini"
    return "openai"


# Platforms in the models.dev catalog that are used through browser/device OAuth
# login (subscription accounts) instead of static API keys.
_OAUTH_PLATFORM_IDS = {"anthropic", "openai", "google", "github-copilot", "qwen", "iflow", "copilot"}


def _auth_type_for(pid: str) -> str:
    return "oauth" if pid in _OAUTH_PLATFORM_IDS else "api_key"


def _normalize(raw: dict) -> list:
    out = []
    for pid, p in raw.items():
        base_url = (p.get("api") or "").strip() or _WELL_KNOWN_API.get(pid, "")
        if not base_url:
            continue  # no API endpoint and no known default -> not usable as an upstream
        npm = p.get("npm") or ""
        models = p.get("models") or {}
        out.append({
            "id": pid,
            "name": p.get("name") or pid,
            "base_url": base_url,
            "protocol": _npm_to_protocol(npm),
            "auth_type": _auth_type_for(pid),
            "description": "",
            "icon": _icon_url(pid),
            "homepage": p.get("doc") or "",
            "models_count": len(models),
        })
    out.sort(key=lambda x: (-x["models_count"], x["name"].lower()))
    return out


def _with_auth_type(providers: list) -> list:
    """Backfill auth_type for caches written before the field existed."""
    for p in providers:
        if "auth_type" not in p:
            p["auth_type"] = _auth_type_for(p.get("id", ""))
    return providers


def _load_cache() -> dict | None:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["providers"] = _with_auth_type(data.get("providers", []))
        return data
    except Exception:
        return None


def _save_cache(data: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def _fetch_and_cache() -> dict:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, trust_env=False) as client:
        resp = await client.get(MODELS_DEV_URL, headers={"User-Agent": "LocalRouter/1.0"})
        resp.raise_for_status()
        raw = resp.json()
    providers = _normalize(raw)
    data = {
        "source": MODELS_DEV_URL,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(providers),
        "providers": providers,
    }
    _save_cache(data)
    return data


@router.get("/online-providers")
async def get_online_providers():
    """Return the cached online provider list; fetch from source on first use."""
    cache = _load_cache()
    if cache:
        return cache
    try:
        return await _fetch_and_cache()
    except Exception:
        return {"source": MODELS_DEV_URL, "updated_at": "", "count": 0, "providers": []}


@router.post("/online-providers/refresh")
async def refresh_online_providers():
    try:
        return await _fetch_and_cache()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch online providers: {str(e)[:200]}")
