from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.provider import Provider
from app.schemas.schemas import ApiKeyCreate, ApiKeyUpdate, ApiKeyOut, ApiKeyTestResult, BatchTestResult, BatchDeleteResult
from app.utils.crypto import encrypt_value, decrypt_value, mask_key
import httpx
import time

router = APIRouter(prefix="/api", tags=["api-keys"])


def _key_to_out(key: ApiKey) -> dict:
    """Convert ApiKey model to output dict with masked key."""
    masked = ""
    decrypted = ""
    if key.key_value:
        try:
            real = decrypt_value(key.key_value)
            masked = mask_key(real)
            decrypted = real
        except Exception:
            masked = "****"
    return ApiKeyOut(
        id=key.id,
        provider_id=key.provider_id,
        key_masked=masked,
        key_value=decrypted,
        alias=key.alias or "",
        status=key.status or "active",
        weight=key.weight or 1,
        last_used_at=key.last_used_at,
        last_error=key.last_error or "",
        created_at=key.created_at,
    ).model_dump()


@router.get("/providers/{provider_id}/keys", response_model=list[ApiKeyOut])
async def list_keys(provider_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiKey).where(ApiKey.provider_id == provider_id).order_by(ApiKey.id)
    )
    keys = result.scalars().all()
    return [_key_to_out(k) for k in keys]


@router.post("/api-keys", response_model=ApiKeyOut, status_code=201)
async def create_key(data: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, data.provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    key = ApiKey(
        provider_id=data.provider_id,
        key_value=encrypt_value(data.key_value),
        alias=data.alias,
        weight=data.weight,
        status="untested",
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return _key_to_out(key)


@router.put("/api-keys/{key_id}", response_model=ApiKeyOut)
async def update_key(key_id: int, data: ApiKeyUpdate, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "API Key not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(key, k, v)
    await db.commit()
    await db.refresh(key)
    return _key_to_out(key)


@router.delete("/api-keys/{key_id}", status_code=204)
async def delete_key(key_id: int, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "API Key not found")
    await db.delete(key)
    await db.commit()


@router.delete("/providers/{provider_id}/keys/invalid", response_model=BatchDeleteResult)
async def delete_invalid_keys(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Delete all inactive/invalid keys for a provider."""
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.provider_id == provider_id,
            ApiKey.status.in_(["inactive", "expired", "rate_limited"])
        )
    )
    keys = result.scalars().all()
    count = len(keys)
    for k in keys:
        await db.delete(k)
    await db.commit()
    return BatchDeleteResult(deleted=count)


@router.post("/providers/{provider_id}/keys/test-all", response_model=BatchTestResult)
async def test_all_keys(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Test all keys for a provider."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.provider_id == provider_id).order_by(ApiKey.id)
    )
    keys = result.scalars().all()
    if not keys:
        return BatchTestResult(total=0, success=0, failed=0, results=[])

    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    success_count = 0
    failed_count = 0
    results = []

    for key in keys:
        test_result = await _test_single_key(key, provider, db)
        if test_result["success"]:
            success_count += 1
        else:
            failed_count += 1
        results.append(test_result)

    return BatchTestResult(
        total=len(keys),
        success=success_count,
        failed=failed_count,
        results=results,
    )


async def _test_single_key(key: ApiKey, provider: Provider, db: AsyncSession) -> dict:
    """Test a single key and update its status."""
    real_key = decrypt_value(key.key_value)
    start = time.monotonic()
    key_id = key.id
    alias = key.alias or ""

    try:
        if provider.protocol == "openai":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{provider.base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {real_key}"},
                )
                elapsed = int((time.monotonic() - start) * 1000)
                if resp.status_code == 200:
                    key.status = "active"
                    key.last_error = None
                    await db.commit()
                    return {"key_id": key_id, "alias": alias, "success": True, "message": "Key is valid", "latency_ms": elapsed}
                else:
                    msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    key.status = "inactive"
                    key.last_error = msg
                    await db.commit()
                    return {"key_id": key_id, "alias": alias, "success": False, "message": msg, "latency_ms": elapsed}

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
                    key.status = "active"
                    key.last_error = None
                    await db.commit()
                    return {"key_id": key_id, "alias": alias, "success": True, "message": "Key is valid", "latency_ms": elapsed}
                else:
                    msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    key.status = "inactive"
                    key.last_error = msg
                    await db.commit()
                    return {"key_id": key_id, "alias": alias, "success": False, "message": msg, "latency_ms": elapsed}

        elif provider.protocol == "gemini":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{provider.base_url.rstrip('/')}/models?key={real_key}",
                )
                elapsed = int((time.monotonic() - start) * 1000)
                if resp.status_code == 200:
                    key.status = "active"
                    key.last_error = None
                    await db.commit()
                    return {"key_id": key_id, "alias": alias, "success": True, "message": "Key is valid", "latency_ms": elapsed}
                else:
                    msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    key.status = "inactive"
                    key.last_error = msg
                    await db.commit()
                    return {"key_id": key_id, "alias": alias, "success": False, "message": msg, "latency_ms": elapsed}

        else:
            return {"key_id": key_id, "alias": alias, "success": False, "message": "Test not supported for custom protocol"}

    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        key.status = "inactive"
        key.last_error = str(e)[:500]
        await db.commit()
        return {"key_id": key_id, "alias": alias, "success": False, "message": str(e)[:200], "latency_ms": elapsed}


@router.post("/api-keys/{key_id}/test", response_model=ApiKeyTestResult)
async def test_key(key_id: int, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "API Key not found")
    provider = await db.get(Provider, key.provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    real_key = decrypt_value(key.key_value)
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
                    key.status = "active"
                    key.last_error = None
                    await db.commit()
                    return ApiKeyTestResult(success=True, message="Key is valid", latency_ms=elapsed)
                else:
                    msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    key.status = "inactive"
                    key.last_error = msg
                    await db.commit()
                    return ApiKeyTestResult(success=False, message=msg, latency_ms=elapsed)

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
                    key.status = "active"
                    key.last_error = None
                    await db.commit()
                    return ApiKeyTestResult(success=True, message="Key is valid", latency_ms=elapsed)
                else:
                    msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    key.status = "inactive"
                    key.last_error = msg
                    await db.commit()
                    return ApiKeyTestResult(success=False, message=msg, latency_ms=elapsed)

        elif provider.protocol == "gemini":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{provider.base_url.rstrip('/')}/models?key={real_key}",
                )
                elapsed = int((time.monotonic() - start) * 1000)
                if resp.status_code == 200:
                    key.status = "active"
                    key.last_error = None
                    await db.commit()
                    return ApiKeyTestResult(success=True, message="Key is valid", latency_ms=elapsed)
                else:
                    msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    key.status = "inactive"
                    key.last_error = msg
                    await db.commit()
                    return ApiKeyTestResult(success=False, message=msg, latency_ms=elapsed)

        else:
            return ApiKeyTestResult(success=False, message="Test not supported for custom protocol")

    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        key.status = "inactive"
        key.last_error = str(e)[:500]
        await db.commit()
        return ApiKeyTestResult(success=False, message=str(e)[:200], latency_ms=elapsed)
