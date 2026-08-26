from fastapi import APIRouter, Depends, HTTPException, Response

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.database import get_db

from app.models.model import Model

from app.models.provider import Provider

from app.models.api_key import ApiKey

from app.schemas.schemas import ModelCreate, ModelUpdate, ModelOut, BatchTestResult, ModelTestResult, BatchDeleteResult, FetchModelItem

from app.utils.crypto import decrypt_value

from app.utils.known_models import get_known_model_params, detect_model_type

import time
import httpx



router = APIRouter(prefix="/api", tags=["models"])





@router.get("/providers/{provider_id}/models", response_model=list[ModelOut])

async def list_models(provider_id: int, db: AsyncSession = Depends(get_db)):

    result = await db.execute(

        select(Model).where(Model.provider_id == provider_id).order_by(Model.id)

    )

    return result.scalars().all()





@router.post("/models", response_model=ModelOut, status_code=201)

async def create_model(data: ModelCreate, db: AsyncSession = Depends(get_db)):

    provider = await db.get(Provider, data.provider_id)

    if not provider:

        raise HTTPException(404, "Provider not found")

    model = Model(**data.model_dump())

    db.add(model)

    await db.commit()

    await db.refresh(model)

    return model





@router.put("/models/{model_id}", response_model=ModelOut)

async def update_model(model_id: int, data: ModelUpdate, db: AsyncSession = Depends(get_db)):

    model = await db.get(Model, model_id)

    if not model:

        raise HTTPException(404, "Model not found")

    for k, v in data.model_dump(exclude_unset=True).items():

        setattr(model, k, v)

    await db.commit()

    await db.refresh(model)

    return model





@router.delete("/models/{model_id}", status_code=204)
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    await db.delete(model)
    await db.commit()
    return Response(status_code=204)





@router.post("/models/fetch/{provider_id}", response_model=list[FetchModelItem])
async def fetch_models(provider_id: int, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    # Get first active key for this provider
    result = await db.execute(
        select(ApiKey).where(ApiKey.provider_id == provider_id, ApiKey.status == "active").limit(1)
    )
    key_obj = result.scalar_one_or_none()

    models_data = []

    try:
        if provider.protocol in ("openai", "custom"):
            headers = {"Content-Type": "application/json"}
            if key_obj:
                headers["Authorization"] = f"Bearer {decrypt_value(key_obj.key_value)}"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{provider.base_url.rstrip('/')}/models", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    # 获取已有模型 id 集合，标记是否已存在
                    existing_result = await db.execute(select(Model).where(Model.provider_id == provider_id))
                    existing_ids = {m.model_id for m in existing_result.scalars().all()}
                    for m in data.get("data", []):
                        mid = m.get("id", "")
                        known = get_known_model_params(mid)
                        models_data.append({
                            "model_id": mid,
                            "display_name": known.get("display_name", mid),
                            "is_multimodal": known.get("is_multimodal", False),
                            "model_type": known.get("model_type", detect_model_type(mid)),
                            "context_window": known.get("context_window"),
                            "temperature": known.get("temperature"),
                            "price_input": known.get("price_input"),
                            "price_output": known.get("price_output"),
                            "already_added": mid in existing_ids,
                        })

        elif provider.protocol == "gemini":
            if not key_obj:
                raise HTTPException(400, "No active API key for this provider")
            real_key = decrypt_value(key_obj.key_value)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{provider.base_url.rstrip('/')}/models?key={real_key}")
                if resp.status_code == 200:
                    data = resp.json()
                    existing_result = await db.execute(select(Model).where(Model.provider_id == provider_id))
                    existing_ids = {m.model_id for m in existing_result.scalars().all()}
                    for m in data.get("models", []):
                        name = m.get("name", "").replace("models/", "")
                        display = m.get("displayName", name)
                        input_limit = m.get("inputTokenLimit")
                        context = input_limit if input_limit else None
                        is_multi = any(k in name.lower() for k in ["vision", "pro", "flash", "ultra"])
                        known = get_known_model_params(name)
                        models_data.append({
                            "model_id": name,
                            "display_name": known.get("display_name", display),
                            "is_multimodal": known.get("is_multimodal", is_multi),
                            "model_type": known.get("model_type", detect_model_type(name)),
                            "context_window": known.get("context_window", context),
                            "temperature": known.get("temperature"),
                            "price_input": known.get("price_input"),
                            "price_output": known.get("price_output"),
                            "already_added": name in existing_ids,
                        })

    except httpx.RequestError:
        pass

    return models_data


@router.post("/models/sync/{provider_id}", response_model=list[ModelOut])

async def sync_models(provider_id: int, db: AsyncSession = Depends(get_db)):

    provider = await db.get(Provider, provider_id)

    if not provider:

        raise HTTPException(404, "Provider not found")



    # Get first active key for this provider

    result = await db.execute(

        select(ApiKey).where(ApiKey.provider_id == provider_id, ApiKey.status == "active").limit(1)

    )

    key_obj = result.scalar_one_or_none()



    models_data = []



    try:

        if provider.protocol in ("openai", "custom"):

            headers = {"Content-Type": "application/json"}

            if key_obj:

                headers["Authorization"] = f"Bearer {decrypt_value(key_obj.key_value)}"

            async with httpx.AsyncClient(timeout=15) as client:

                resp = await client.get(f"{provider.base_url.rstrip('/')}/models", headers=headers)

                if resp.status_code == 200:

                    data = resp.json()

                    for m in data.get("data", []):

                        mid = m.get("id", "")

                        known = get_known_model_params(mid)

                        models_data.append({

                            "model_id": mid,

                            "display_name": known.get("display_name", mid),

                            "is_multimodal": known.get("is_multimodal", False),

                            "model_type": known.get("model_type", detect_model_type(mid)),

                            "context_window": known.get("context_window"),

                            "temperature": known.get("temperature"),

                            "price_input": known.get("price_input"),

                            "price_output": known.get("price_output"),

                        })



        elif provider.protocol == "gemini":

            if not key_obj:

                raise HTTPException(400, "No active API key for this provider")

            real_key = decrypt_value(key_obj.key_value)

            async with httpx.AsyncClient(timeout=15) as client:

                resp = await client.get(f"{provider.base_url.rstrip('/')}/models?key={real_key}")

                if resp.status_code == 200:

                    data = resp.json()

                    for m in data.get("models", []):

                        name = m.get("name", "").replace("models/", "")

                        display = m.get("displayName", name)

                        # Extract Gemini-specific parameters

                        input_limit = m.get("inputTokenLimit")

                        output_limit = m.get("outputTokenLimit")

                        context = None

                        if input_limit:

                            context = input_limit

                        elif output_limit:

                            context = output_limit

                        # Detect multimodal from supported methods

                        methods = m.get("supportedGenerationMethods", [])

                        is_multi = any(k in name.lower() for k in ["vision", "pro", "flash", "ultra"])

                        # Try known params first

                        known = get_known_model_params(name)

                        models_data.append({

                            "model_id": name,

                            "display_name": known.get("display_name", display),

                            "is_multimodal": known.get("is_multimodal", is_multi),

                            "model_type": known.get("model_type", detect_model_type(name)),

                            "context_window": known.get("context_window", context),

                            "temperature": known.get("temperature"),

                            "price_input": known.get("price_input"),

                            "price_output": known.get("price_output"),

                        })



    except httpx.RequestError:

        pass



    # Upsert models - preserve manual edits, update synced fields

    existing_result = await db.execute(select(Model).where(Model.provider_id == provider_id))

    existing = {m.model_id: m for m in existing_result.scalars().all()}



    # Enrich existing models that have empty params from known database

    for mid, m in existing.items():

        if not m.context_window and not m.price_input:

            known = get_known_model_params(mid)

            if known:

                if known.get("is_multimodal"):

                    m.is_multimodal = True

                if known.get("model_type") and m.model_type == "text":

                    m.model_type = known["model_type"]

                if known.get("context_window"):

                    m.context_window = known["context_window"]

                if known.get("temperature") is not None:

                    m.temperature = known["temperature"]

                if known.get("price_input") is not None:

                    m.price_input = known["price_input"]

                if known.get("price_output") is not None:

                    m.price_output = known["price_output"]

                if known.get("display_name"):

                    m.display_name = known["display_name"]



    created = []

    for md in models_data:

        if md["model_id"] in existing:

            m = existing[md["model_id"]]

            # Only update fields if they are not empty/default

            m.display_name = md["display_name"] or m.display_name

            if md["is_multimodal"]:

                m.is_multimodal = True

            if md["model_type"] and md["model_type"] != "text":

                m.model_type = md["model_type"]

            if md["context_window"]:

                m.context_window = md["context_window"]

            if md["temperature"] is not None:

                m.temperature = md["temperature"]

            if md["price_input"] is not None:

                m.price_input = md["price_input"]

            if md["price_output"] is not None:

                m.price_output = md["price_output"]

            created.append(m)

        else:

            new_model = Model(

                provider_id=provider_id,

                model_id=md["model_id"],

                display_name=md["display_name"],

                is_multimodal=md.get("is_multimodal", False),

                model_type=md.get("model_type", "text"),

                context_window=md.get("context_window"),

                temperature=md.get("temperature"),

                price_input=md.get("price_input"),

                price_output=md.get("price_output"),

            )

            db.add(new_model)

            created.append(new_model)



    await db.commit()

    for m in created:

        await db.refresh(m)

    return created


@router.post("/providers/{provider_id}/models/test-all", response_model=BatchTestResult)
async def test_all_models(provider_id: int, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    result = await db.execute(
        select(Model).where(Model.provider_id == provider_id, Model.is_active == True)
    )
    models = result.scalars().all()
    model_map = {m.model_id: m for m in models}
    if not models:
        return BatchTestResult(total=0, success=0, failed=0, results=[])

    key_result = await db.execute(
        select(ApiKey).where(ApiKey.provider_id == provider_id, ApiKey.status == "active").limit(1)
    )
    key_obj = key_result.scalar_one_or_none()

    results: list[ModelTestResult] = []
    success_count = 0
    failed_count = 0

    async with httpx.AsyncClient(timeout=15) as client:
        for model in models:
            start = time.time()
            try:
                if provider.protocol in ("openai", "custom"):
                    headers = {"Content-Type": "application/json"}
                    if key_obj:
                        headers["Authorization"] = f"Bearer {decrypt_value(key_obj.key_value)}"
                    payload = {
                        "model": model.model_id,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    }
                    resp = await client.post(
                        f"{provider.base_url.rstrip('/')}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    ok = resp.status_code == 200
                    msg = "OK" if ok else f"HTTP {resp.status_code}"

                elif provider.protocol == "claude":
                    headers = {
                        "Content-Type": "application/json",
                        "x-api-key": decrypt_value(key_obj.key_value) if key_obj else "",
                        "anthropic-version": "2023-06-01",
                    }
                    payload = {
                        "model": model.model_id,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    }
                    resp = await client.post(
                        f"{provider.base_url.rstrip('/')}/messages",
                        json=payload,
                        headers=headers,
                    )
                    ok = resp.status_code == 200
                    msg = "OK" if ok else f"HTTP {resp.status_code}"

                elif provider.protocol == "gemini":
                    real_key = decrypt_value(key_obj.key_value) if key_obj else ""
                    payload = {
                        "contents": [{"parts": [{"text": "hi"}]}],
                        "generationConfig": {"maxOutputTokens": 1},
                    }
                    resp = await client.post(
                        f"{provider.base_url.rstrip('/')}/models/{model.model_id}:generateContent?key={real_key}",
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    ok = resp.status_code == 200
                    msg = "OK" if ok else f"HTTP {resp.status_code}"

                else:
                    ok = False
                    msg = "Unsupported protocol"

            except Exception as e:
                ok = False
                msg = str(e)

            latency = int((time.time() - start) * 1000)
            results.append(ModelTestResult(
                model_id=model.model_id,
                success=ok,
                message=msg,
                latency_ms=latency,
            ))
            db_model = model_map.get(model.model_id)
            if db_model:
                if ok:
                    db_model.status = "active"
                    db_model.last_error = ""
                else:
                    db_model.status = "inactive"
                    db_model.last_error = msg[:500]
            if ok:
                success_count += 1
            else:
                failed_count += 1

    await db.commit()

    return BatchTestResult(
        total=len(models),
        success=success_count,
        failed=failed_count,
        results=results,
    )


@router.delete("/providers/{provider_id}/models/invalid", response_model=BatchDeleteResult)
async def delete_invalid_models(provider_id: int, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    # 删除当前平台下所有 status 为 "inactive" 的模型（由"测试全部模型"标记的无效模型）
    result = await db.execute(
        select(Model).where(Model.provider_id == provider_id, Model.status == "inactive")
    )
    invalid_models = result.scalars().all()

    deleted_count = 0
    for m in invalid_models:
        await db.delete(m)
        deleted_count += 1

    if deleted_count > 0:
        await db.commit()

    return BatchDeleteResult(deleted=deleted_count)


@router.delete("/providers/{provider_id}/models", response_model=BatchDeleteResult)
async def clear_models(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Delete all models for a provider."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    result = await db.execute(
        select(Model).where(Model.provider_id == provider_id)
    )
    models = result.scalars().all()

    deleted_count = 0
    for m in models:
        await db.delete(m)
        deleted_count += 1

    if deleted_count > 0:
        await db.commit()

    return BatchDeleteResult(deleted=deleted_count)
