"""
API Key health check utilities.
"""
import time
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.api_key import ApiKey
from app.models.provider import Provider
from app.utils.crypto import decrypt_value


async def check_key_health(db: AsyncSession, api_key: ApiKey, provider: Provider) -> dict:
    """Test if an API key is working. Returns {success, message, latency_ms}."""
    real_key = decrypt_value(api_key.key_value)
    start = time.monotonic()

    try:
        if provider.protocol == "openai":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{provider.base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {real_key}"},
                )
                elapsed = int((time.monotonic() - start) * 1000)
                if resp.status_code == 200:
                    return {"success": True, "message": "OK", "latency_ms": elapsed}
                return {"success": False, "message": f"HTTP {resp.status_code}", "latency_ms": elapsed}

        elif provider.protocol == "claude":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{provider.base_url.rstrip('/')}/messages",
                    headers={
                        "x-api-key": real_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={"model": "claude-3-haiku-20240307", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
                )
                elapsed = int((time.monotonic() - start) * 1000)
                if resp.status_code == 200:
                    return {"success": True, "message": "OK", "latency_ms": elapsed}
                return {"success": False, "message": f"HTTP {resp.status_code}", "latency_ms": elapsed}

        elif provider.protocol == "gemini":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{provider.base_url.rstrip('/')}/models?key={real_key}",
                )
                elapsed = int((time.monotonic() - start) * 1000)
                if resp.status_code == 200:
                    return {"success": True, "message": "OK", "latency_ms": elapsed}
                return {"success": False, "message": f"HTTP {resp.status_code}", "latency_ms": elapsed}

        return {"success": False, "message": "Unsupported protocol"}

    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return {"success": False, "message": str(e)[:200], "latency_ms": elapsed}


async def batch_check_keys(db: AsyncSession, provider_id: int) -> list[dict]:
    """Check all keys for a provider. Returns list of {key_id, success, message, latency_ms}."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.provider_id == provider_id, ApiKey.status == "active")
    )
    keys = result.scalars().all()
    provider = await db.get(Provider, provider_id)
    if not provider:
        return []

    results = []
    for key in keys:
        check = await check_key_health(db, key, provider)
        if check["success"]:
            key.status = "active"
            key.last_error = None
        else:
            key.status = "inactive"
            key.last_error = check["message"]
        await db.commit()
        results.append({"key_id": key.id, **check})

    return results
