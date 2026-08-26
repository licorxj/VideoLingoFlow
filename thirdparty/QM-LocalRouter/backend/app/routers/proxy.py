import json
import time
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.strategy import Strategy, StrategyRule
from app.models.provider import Provider
from app.models.model import Model
from app.models.api_key import ApiKey
from app.services.balancer import Balancer, _rule_token_tracker
from app.services.forwarder import Forwarder
from app.utils.protocol_adapter import (claude_response_to_openai, gemini_response_to_openai, openai_to_claude_response, openai_to_gemini_response, convert_openai_stream_to_claude_chunks, convert_openai_stream_to_gemini_chunks)
from app.routers.settings import get_output_protocol
import httpx

router = APIRouter(tags=["proxy"])


async def _resolve(strategy_name: str, db: AsyncSession):
    """Resolve strategy by name."""
    result = await db.execute(
        select(Strategy).options(selectinload(Strategy.rules)).where(
            Strategy.name == strategy_name, Strategy.is_active == True
        )
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(404, detail=f"Strategy '{strategy_name}' not found or inactive")
    return strategy


async def _try_forward(strategy, db, request_body, is_stream):
    """Try to forward request using balancer with retry logic."""
    balancer = Balancer(db)
    forwarder = Forwarder(db)
    last_error = None

    for attempt in range(strategy.retry_count + 1):
        rule = await balancer.select_rule(strategy)
        if not rule:
            raise HTTPException(503, detail="No active rules in strategy")

        provider = await db.get(Provider, rule.provider_id)
        model = await db.get(Model, rule.model_id)
        if not provider or not model or not provider.is_active or not model.is_active:
            last_error = "Provider or model unavailable"
            continue

        api_key = await balancer.select_key(provider.id, strategy)
        if not api_key:
            last_error = f"No active API key for {provider.name}"
            continue

        try:
            if is_stream:
                return await _handle_stream(strategy, rule, provider, model, api_key, request_body, forwarder, db)
            else:
                return await _handle_non_stream(strategy, rule, provider, model, api_key, request_body, forwarder, db)
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            last_error = str(e)[:500]
            if isinstance(e, httpx.HTTPStatusError):
                if e.response.status_code == 429:
                    api_key.status = "rate_limited"
                    api_key.last_error = "Rate limited"
                    await db.commit()
                elif e.response.status_code in (401, 403):
                    api_key.status = "inactive"
                    api_key.last_error = f"Auth error: {e.response.status_code}"
                    await db.commit()
            continue
        except Exception as e:
            last_error = str(e)[:500]
            continue

    try:
        await forwarder.log_request(
            strategy.id, None, None, str(last_error)[:100],
            request_body, 502, 0, is_stream, str(last_error)[:500],
        )
    except Exception:
        pass

    raise HTTPException(502, detail=f"All attempts failed: {last_error}")


async def _handle_stream(strategy, rule, provider, model, api_key, request_body, forwarder, db):
    start = time.monotonic()

    token_counter = {"prompt": 0, "completion": 0}

    output_proto = get_output_protocol()
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    async def generate():
        try:
            async for chunk in forwarder.forward_stream(strategy, rule, provider, model, api_key, request_body):
                if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                    try:
                        import json as _json
                        obj = _json.loads(chunk[6:])
                        u = obj.get("usage")
                        if u:
                            token_counter["prompt"] = u.get("prompt_tokens", 0) or 0
                            token_counter["completion"] = u.get("completion_tokens", 0) or 0
                    except Exception:
                        pass
                if output_proto != "openai" and chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                    try:
                        import json as _json
                        obj = _json.loads(chunk[6:])
                        if output_proto == "claude":
                            converted = convert_openai_stream_to_claude_chunks(obj, completion_id)
                            if converted:
                                yield converted
                                continue
                        elif output_proto == "gemini":
                            converted = convert_openai_stream_to_gemini_chunks(obj)
                            if converted:
                                yield converted
                                continue
                    except Exception:
                        pass
                yield chunk
            latency = int((time.monotonic() - start) * 1000)
            total = token_counter["prompt"] + token_counter["completion"]
            await forwarder.log_request(
                strategy.id, provider.id, api_key.id, model.model_id,
                request_body, 200, latency, True, None,
                prompt_tokens=token_counter["prompt"], completion_tokens=token_counter["completion"], total_tokens=total,
            )
            if strategy.lb_strategy == "token_threshold" and total > 0:
                _rule_token_tracker.record_usage(
                    strategy.id, rule.id, total, strategy.rule_token_period or "per_day"
                )
            api_key.last_used_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            await forwarder.log_request(
                strategy.id, provider.id, api_key.id, model.model_id,
                request_body, 500, latency, True, str(e)[:500],
            )
            yield f"data: {json.dumps({'error': {'message': str(e)[:200]}})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _handle_non_stream(strategy, rule, provider, model, api_key, request_body, forwarder, db):
    start = time.monotonic()
    resp = await forwarder.forward(strategy, rule, provider, model, api_key, request_body, is_stream=False)
    latency = int((time.monotonic() - start) * 1000)

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    if resp.status_code >= 400:
        await forwarder.log_request(
            strategy.id, provider.id, api_key.id, model.model_id,
            request_body, resp.status_code, latency, False, resp.text[:500],
        )
        return JSONResponse(status_code=resp.status_code, content={"error": {"message": resp.text[:500]}})

    data = resp.json()

    if provider.protocol == "claude":
        data = claude_response_to_openai(data, model.model_id)
    elif provider.protocol == "gemini":
        data = gemini_response_to_openai(data, model.model_id)

    output_proto = get_output_protocol()
    if output_proto == "claude":
        data = openai_to_claude_response(data)
    elif output_proto == "gemini":
        data = openai_to_gemini_response(data)

    usage = data.get("usage", {})
    prompt_tok = usage.get("prompt_tokens", 0) or 0
    completion_tok = usage.get("completion_tokens", 0) or 0
    total_tok = usage.get("total_tokens", 0) or (prompt_tok + completion_tok)

    await forwarder.log_request(
        strategy.id, provider.id, api_key.id, model.model_id,
        request_body, 200, latency, False, None,
        prompt_tokens=prompt_tok, completion_tokens=completion_tok, total_tokens=total_tok,
    )
    if strategy.lb_strategy == "token_threshold" and total_tok > 0:
        _rule_token_tracker.record_usage(
            strategy.id, rule.id, total_tok, strategy.rule_token_period or "per_day"
        )
    return JSONResponse(content=data)


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    model_name = body.get("model", "")
    is_stream = body.get("stream", False)

    # Direct model mode: bypass strategy lookup
    direct_provider_id = body.pop("_direct_provider_id", None)
    if direct_provider_id:
        provider = await db.get(Provider, int(direct_provider_id))
        if not provider or not provider.is_active:
            raise HTTPException(404, detail=f"Provider '{direct_provider_id}' not found or inactive")
        # Find the model by model_id
        result = await db.execute(
            select(Model).where(Model.provider_id == int(direct_provider_id), Model.model_id == model_name)
        )
        model_obj = result.scalar_one_or_none()
        if not model_obj:
            # Try by display_name
            result2 = await db.execute(
                select(Model).where(Model.provider_id == int(direct_provider_id), Model.display_name == model_name)
            )
            model_obj = result2.scalar_one_or_none()
        if not model_obj or not model_obj.is_active:
            raise HTTPException(404, detail=f"Model '{model_name}' not found or inactive for provider {provider.name}")

        # Select an API key
        key_result = await db.execute(
            select(ApiKey).where(ApiKey.provider_id == int(direct_provider_id), ApiKey.status == "active")
        )
        api_key = key_result.scalars().first()
        if not api_key:
            raise HTTPException(503, detail=f"No active API key for provider {provider.name}")

        # Create pseudo-strategy and rule for forwarding
        pseudo_strategy = Strategy(
            id=0, name=f"__direct__{provider.name}__{model_name}",
            lb_strategy="round_robin", is_active=True,
            timeout=120, retry_count=0,
        )
        pseudo_rule = StrategyRule(
            id=0, strategy_id=0, provider_id=provider.id,
            model_id=model_obj.id, priority=1, weight=1, is_active=True,
        )
        pseudo_strategy.rules = [pseudo_rule]

        forwarder = Forwarder(db)
        if is_stream:
            return await _handle_stream(pseudo_strategy, pseudo_rule, provider, model_obj, api_key, body, forwarder, db)
        else:
            return await _handle_non_stream(pseudo_strategy, pseudo_rule, provider, model_obj, api_key, body, forwarder, db)

    # Normal strategy mode
    strategy = await _resolve(model_name, db)
    return await _try_forward(strategy, db, body, is_stream)


@router.post("/v1/completions")
async def completions(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    prompt = body.get("prompt", "")
    model_name = body.get("model", "")
    chat_body = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": body.get("max_tokens", 1024),
        "stream": body.get("stream", False),
    }
    strategy = await _resolve(model_name, db)
    return await _try_forward(strategy, db, chat_body, body.get("stream", False))


@router.get("/v1/models")
async def list_available_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Strategy).where(Strategy.is_active == True))
    strategies = result.scalars().all()
    return {
        "object": "list",
        "data": [
            {
                "id": s.name,
                "object": "model",
                "created": int(s.created_at.timestamp()) if s.created_at else 0,
                "owned_by": "router",
            }
            for s in strategies
        ],
    }


# ============================================================
# Image Generation Proxy
# ============================================================

async def _resolve_model_from_provider(model_name: str, provider_id: int, db: AsyncSession):
    """Find model by model_id within a provider."""
    result = await db.execute(
        select(Model).where(Model.provider_id == provider_id, Model.model_id == model_name)
    )
    model_obj = result.scalar_one_or_none()
    if not model_obj:
        result2 = await db.execute(
            select(Model).where(Model.provider_id == provider_id, Model.display_name == model_name)
        )
        model_obj = result2.scalar_one_or_none()
    return model_obj


async def _select_key_for_provider(provider_id: int, db: AsyncSession):
    """Select first active API key for a provider."""
    key_result = await db.execute(
        select(ApiKey).where(ApiKey.provider_id == provider_id, ApiKey.status == "active")
    )
    return key_result.scalars().first()


async def _find_provider_and_model_for_image(model_name: str, provider_id: int | None, db: AsyncSession):
    """Resolve provider and model for image generation.

    If provider_id is given, look up within that provider.
    Otherwise, search all providers for a model matching model_name with model_type=image.
    """
    if provider_id:
        provider = await db.get(Provider, int(provider_id))
        if not provider or not provider.is_active:
            raise HTTPException(404, detail=f"Provider '{provider_id}' not found or inactive")
        model_obj = await _resolve_model_from_provider(model_name, provider.id, db)
        if not model_obj:
            raise HTTPException(404, detail=f"Model '{model_name}' not found for provider {provider.name}")
        return provider, model_obj

    # Search across all providers for this image model
    result = await db.execute(
        select(Model).where(Model.model_id == model_name, Model.model_type == "image", Model.is_active == True)
    )
    model_obj = result.scalars().first()
    if not model_obj:
        # Try display_name
        result2 = await db.execute(
            select(Model).where(Model.display_name == model_name, Model.model_type == "image", Model.is_active == True)
        )
        model_obj = result2.scalars().first()
    if not model_obj:
        raise HTTPException(404, detail=f"Image model '{model_name}' not found in any active provider")

    provider = await db.get(Provider, model_obj.provider_id)
    if not provider or not provider.is_active:
        raise HTTPException(404, detail=f"Provider for model '{model_name}' is not active")
    return provider, model_obj


@router.post("/v1/images/generations")
async def image_generations(request: Request, db: AsyncSession = Depends(get_db)):
    """OpenAI-compatible image generation proxy.

    Accepts standard OpenAI /v1/images/generations body and routes to the
    appropriate upstream provider based on model_type=image.
    Supports optional _direct_provider_id in body for direct mode.
    """
    body = await request.json()
    model_name = body.pop("model", "")
    direct_provider_id = body.pop("_direct_provider_id", None)

    provider, model_obj = await _find_provider_and_model_for_image(
        model_name, int(direct_provider_id) if direct_provider_id else None, db
    )

    api_key = await _select_key_for_provider(provider.id, db)
    if not api_key:
        raise HTTPException(503, detail=f"No active API key for provider {provider.name}")

    forwarder = Forwarder(db)

    try:
        resp = await forwarder.forward_image(provider, model_obj, api_key, body)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(502, detail=f"Image generation failed: {str(e)[:500]}")

    if resp.status_code != 200:
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": resp.text[:500]}},
        )

    # Convert response to OpenAI format
    data = resp.json()
    from app.utils.protocol_adapter import gemini_image_response_to_openai

    if provider.protocol == "gemini":
        openai_resp = gemini_image_response_to_openai(data, model_obj.model_id, body.get("prompt", ""))
        return JSONResponse(content=openai_resp)

    # For openai/custom protocol, pass through as-is (already OpenAI format)
    return JSONResponse(content=data)


# ============================================================
# TTS (Text-to-Speech) Proxy
# ============================================================

async def _find_provider_and_model_for_tts(model_name: str, provider_id: int | None, db: AsyncSession):
    """Resolve provider and model for TTS."""
    if provider_id:
        provider = await db.get(Provider, int(provider_id))
        if not provider or not provider.is_active:
            raise HTTPException(404, detail=f"Provider '{provider_id}' not found or inactive")
        model_obj = await _resolve_model_from_provider(model_name, provider.id, db)
        if not model_obj:
            raise HTTPException(404, detail=f"Model '{model_name}' not found for provider {provider.name}")
        return provider, model_obj

    result = await db.execute(
        select(Model).where(Model.model_id == model_name, Model.model_type == "tts", Model.is_active == True)
    )
    model_obj = result.scalars().first()
    if not model_obj:
        result2 = await db.execute(
            select(Model).where(Model.display_name == model_name, Model.model_type == "tts", Model.is_active == True)
        )
        model_obj = result2.scalars().first()
    if not model_obj:
        raise HTTPException(404, detail=f"TTS model '{model_name}' not found in any active provider")

    provider = await db.get(Provider, model_obj.provider_id)
    if not provider or not provider.is_active:
        raise HTTPException(404, detail=f"Provider for TTS model '{model_name}' is not active")
    return provider, model_obj


@router.post("/v1/audio/speech")
async def audio_speech(request: Request, db: AsyncSession = Depends(get_db)):
    """OpenAI-compatible TTS proxy.

    Accepts standard OpenAI /v1/audio/speech body (model, input, voice, response_format, speed).
    Returns raw audio bytes.
    """
    body = await request.json()
    model_name = body.pop("model", "")
    direct_provider_id = body.pop("_direct_provider_id", None)

    provider, model_obj = await _find_provider_and_model_for_tts(
        model_name, int(direct_provider_id) if direct_provider_id else None, db
    )

    api_key = await _select_key_for_provider(provider.id, db)
    if not api_key:
        raise HTTPException(503, detail=f"No active API key for provider {provider.name}")

    forwarder = Forwarder(db)

    try:
        resp, content_type = await forwarder.forward_tts(provider, model_obj, api_key, body)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(502, detail=f"TTS request failed: {str(e)[:500]}")

    if resp.status_code != 200:
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": resp.text[:500]}},
        )

    # Return raw audio bytes
    from fastapi.responses import Response
    return Response(content=resp.content, media_type=content_type)


# ============================================================
# Video Generation Proxy
# ============================================================

async def _find_provider_and_model_for_video(model_name: str, provider_id: int | None, db: AsyncSession):
    """Resolve provider and model for video generation."""
    if provider_id:
        provider = await db.get(Provider, int(provider_id))
        if not provider or not provider.is_active:
            raise HTTPException(404, detail=f"Provider '{provider_id}' not found or inactive")
        model_obj = await _resolve_model_from_provider(model_name, provider.id, db)
        if not model_obj:
            raise HTTPException(404, detail=f"Model '{model_name}' not found for provider {provider.name}")
        return provider, model_obj

    result = await db.execute(
        select(Model).where(Model.model_id == model_name, Model.model_type == "video", Model.is_active == True)
    )
    model_obj = result.scalars().first()
    if not model_obj:
        result2 = await db.execute(
            select(Model).where(Model.display_name == model_name, Model.model_type == "video", Model.is_active == True)
        )
        model_obj = result2.scalars().first()
    if not model_obj:
        raise HTTPException(404, detail=f"Video model '{model_name}' not found in any active provider")

    provider = await db.get(Provider, model_obj.provider_id)
    if not provider or not provider.is_active:
        raise HTTPException(404, detail=f"Provider for video model '{model_name}' is not active")
    return provider, model_obj


@router.post("/v1/videos")
async def video_generations(request: Request, db: AsyncSession = Depends(get_db)):
    """Video generation proxy (create task).

    Accepts body with model, prompt, optional image/images, mode, etc.
    Returns a video generation task object.
    """
    body = await request.json()
    model_name = body.pop("model", "")
    direct_provider_id = body.pop("_direct_provider_id", None)

    provider, model_obj = await _find_provider_and_model_for_video(
        model_name, int(direct_provider_id) if direct_provider_id else None, db
    )

    api_key = await _select_key_for_provider(provider.id, db)
    if not api_key:
        raise HTTPException(503, detail=f"No active API key for provider {provider.name}")

    forwarder = Forwarder(db)

    try:
        resp = await forwarder.forward_video(provider, model_obj, api_key, body)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(502, detail=f"Video generation failed: {str(e)[:500]}")

    if resp.status_code not in (200, 201, 202):
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": resp.text[:500]}},
        )

    data = resp.json()
    from app.utils.protocol_adapter import video_response_to_openai
    normalized = video_response_to_openai(data)
    return JSONResponse(content=normalized)


@router.get("/v1/videos/{task_id}")
async def video_task_status(task_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Retrieve video generation task status.

    Requires _provider_id query param to know which provider to query.
    """
    provider_id = request.query_params.get("_provider_id")
    if not provider_id:
        raise HTTPException(400, detail="Missing _provider_id query parameter")

    provider = await db.get(Provider, int(provider_id))
    if not provider or not provider.is_active:
        raise HTTPException(404, detail=f"Provider '{provider_id}' not found or inactive")

    api_key = await _select_key_for_provider(provider.id, db)
    if not api_key:
        raise HTTPException(503, detail=f"No active API key for provider {provider.name}")

    forwarder = Forwarder(db)

    try:
        resp = await forwarder.forward_video_get(provider, api_key, task_id)
    except Exception as e:
        raise HTTPException(502, detail=f"Video task retrieval failed: {str(e)[:500]}")

    if resp.status_code != 200:
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": {"message": resp.text[:500]}},
        )

    data = resp.json()
    from app.utils.protocol_adapter import video_response_to_openai
    normalized = video_response_to_openai(data, task_id)
    return JSONResponse(content=normalized)


# ============================================================
# Multi-Forward: 同时向多个端点发送请求
# ============================================================

@router.post("/v1/multi/chat/completions")
async def multi_chat_completions(request: Request, db: AsyncSession = Depends(get_db)):
    """
    同时向多个端点发送相同的聊天请求

    请求体格式:
    {
        "targets": [
            {"strategy": "strategy_name"},
            {"provider_id": 1, "model_id": "gpt-4o"}
        ],
        "messages": [{"role": "user", "content": "..."}],
        "options": {
            "temperature": 0.7,
            "max_tokens": 1000
        }
    }

    返回格式:
    {
        "results": [
            {"target": "strategy_name", "success": true, "content": "..."},
            {"target": "provider_id:1", "success": false, "error": "..."}
        ]
    }
    """
    body = await request.json()
    targets_config = body.get("targets", [])
    messages = body.get("messages", [])
    options = body.get("options", {})

    if not targets_config:
        raise HTTPException(400, detail="No targets specified")

    if not messages:
        raise HTTPException(400, detail="No messages provided")

    forwarder = Forwarder(db)
    results = []

    for target in targets_config:
        try:
            if "strategy" in target:
                # 通过策略路由
                strategy_name = target["strategy"]
                strategy = await _resolve(strategy_name, db)
                balancer = Balancer(db)

                rule = await balancer.select_rule(strategy)
                if not rule:
                    results.append({
                        "target": strategy_name,
                        "success": False,
                        "error": "No active rules in strategy"
                    })
                    continue

                provider = await db.get(Provider, rule.provider_id)
                model = await db.get(Model, rule.model_id)
                if not provider or not model:
                    results.append({
                        "target": strategy_name,
                        "success": False,
                        "error": "Provider or model not found"
                    })
                    continue

                api_key = await balancer.select_key(provider.id, strategy)
                if not api_key:
                    results.append({
                        "target": strategy_name,
                        "success": False,
                        "error": f"No active API key for {provider.name}"
                    })
                    continue

                # 使用 litellm 转发
                request_body = {
                    "messages": messages,
                    **options
                }

                # 检查是否使用 litellm
                use_litellm = target.get("use_litellm", True)
                if use_litellm:
                    response = await forwarder.forward_with_litellm(
                        provider, model, api_key, request_body, timeout=strategy.timeout or 120
                    )
                    content = response.choices[0].message.content
                else:
                    response = await forwarder.forward(
                        strategy, rule, provider, model, api_key, request_body, is_stream=False
                    )
                    data = response.json()
                    if provider.protocol == "claude":
                        data = claude_response_to_openai(data, model.model_id)
                    elif provider.protocol == "gemini":
                        data = gemini_response_to_openai(data, model.model_id)
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                results.append({
                    "target": strategy_name,
                    "success": True,
                    "provider": provider.name,
                    "model": model.model_id,
                    "content": content
                })

            elif "provider_id" in target:
                # 直接指定 provider 和 model
                provider_id = target["provider_id"]
                model_name = target.get("model_id", target.get("model"))

                provider = await db.get(Provider, int(provider_id))
                if not provider or not provider.is_active:
                    results.append({
                        "target": f"provider_id:{provider_id}",
                        "success": False,
                        "error": "Provider not found or inactive"
                    })
                    continue

                # 查找模型
                model_result = await db.execute(
                    select(Model).where(
                        Model.provider_id == provider.id,
                        (Model.model_id == model_name) | (Model.display_name == model_name),
                        Model.is_active == True
                    )
                )
                model_obj = model_result.scalar_one_or_none()
                if not model_obj:
                    results.append({
                        "target": f"provider_id:{provider_id}",
                        "success": False,
                        "error": f"Model '{model_name}' not found"
                    })
                    continue

                # 选择 API key
                api_key = await _select_key_for_provider(provider.id, db)
                if not api_key:
                    results.append({
                        "target": f"provider_id:{provider_id}",
                        "success": False,
                        "error": f"No active API key"
                    })
                    continue

                request_body = {
                    "messages": messages,
                    **options
                }

                use_litellm = target.get("use_litellm", True)
                if use_litellm:
                    response = await forwarder.forward_with_litellm(
                        provider, model_obj, api_key, request_body
                    )
                    content = response.choices[0].message.content
                else:
                    response = await forwarder.forward(
                        Strategy(), None, provider, model_obj, api_key, request_body, is_stream=False
                    )
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                results.append({
                    "target": f"{provider.name}/{model_obj.model_id}",
                    "success": True,
                    "provider": provider.name,
                    "model": model_obj.model_id,
                    "content": content
                })

            else:
                results.append({
                    "target": str(target),
                    "success": False,
                    "error": "Invalid target format"
                })

        except Exception as e:
            results.append({
                "target": str(target),
                "success": False,
                "error": str(e)[:500]
            })

    return JSONResponse(content={"results": results})


@router.post("/v1/multi/stream/chat/completions")
async def multi_stream_chat_completions(request: Request, db: AsyncSession = Depends(get_db)):
    """
    同时向多个端点发送相同的聊天请求，流式返回第一个成功的响应

    请求体格式:
    {
        "targets": [
            {"strategy": "strategy_name"},
            {"provider_id": 1, "model_id": "gpt-4o"}
        ],
        "messages": [{"role": "user", "content": "..."}],
        "options": {...}
    }

    响应: SSE 流，第一个成功的响应
    """
    body = await request.json()
    targets_config = body.get("targets", [])
    messages = body.get("messages", [])
    options = body.get("options", {})

    if not targets_config:
        raise HTTPException(400, detail="No targets specified")

    if not messages:
        raise HTTPException(400, detail="No messages provided")

    async def generate():
        for target in targets_config:
            try:
                if "strategy" in target:
                    strategy_name = target["strategy"]
                    strategy = await _resolve(strategy_name, db)
                    balancer = Balancer(db)
                    forwarder = Forwarder(db)

                    rule = await balancer.select_rule(strategy)
                    if not rule:
                        continue

                    provider = await db.get(Provider, rule.provider_id)
                    model = await db.get(Model, rule.model_id)
                    if not provider or not model:
                        continue

                    api_key = await balancer.select_key(provider.id, strategy)
                    if not api_key:
                        continue

                    request_body = {"messages": messages, **options}

                    use_litellm = target.get("use_litellm", True)
                    if use_litellm:
                        async for chunk in forwarder.forward_stream_with_litellm(
                            provider, model, api_key, request_body, timeout=strategy.timeout or 120
                        ):
                            yield f"target: {strategy_name}\n".encode() + chunk.encode()
                            return  # 返回第一个成功的响应
                    else:
                        async for chunk in forwarder.forward_stream(strategy, rule, provider, model, api_key, request_body):
                            yield f"target: {strategy_name}\n".encode() + chunk.encode()
                            return

                elif "provider_id" in target:
                    provider_id = target["provider_id"]
                    model_name = target.get("model_id", target.get("model"))

                    provider = await db.get(Provider, int(provider_id))
                    if not provider or not provider.is_active:
                        continue

                    model_result = await db.execute(
                        select(Model).where(
                            Model.provider_id == provider.id,
                            (Model.model_id == model_name) | (Model.display_name == model_name),
                            Model.is_active == True
                        )
                    )
                    model_obj = model_result.scalar_one_or_none()
                    if not model_obj:
                        continue

                    api_key = await _select_key_for_provider(provider.id, db)
                    if not api_key:
                        continue

                    request_body = {"messages": messages, **options}
                    forwarder = Forwarder(db)

                    use_litellm = target.get("use_litellm", True)
                    if use_litellm:
                        async for chunk in forwarder.forward_stream_with_litellm(
                            provider, model_obj, api_key, request_body
                        ):
                            yield f"target: {provider.name}/{model_obj.model_id}\n".encode() + chunk.encode()
                            return
                    else:
                        async for chunk in forwarder.forward_stream(
                            Strategy(), None, provider, model_obj, api_key, request_body
                        ):
                            yield f"target: {provider.name}/{model_obj.model_id}\n".encode() + chunk.encode()
                            return

            except Exception as e:
                continue

        # 所有目标都失败
        yield b'data: {"error": "All targets failed"}\n\n'
        yield b"data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")