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
from app.utils.protocol_adapter import (claude_response_to_openai, gemini_response_to_openai, openai_to_claude_response, openai_to_gemini_response, convert_openai_stream_to_claude_chunks, convert_openai_stream_to_gemini_chunks, responses_request_to_chat, chat_completion_to_response, ResponsesStreamWriter, claude_request_to_chat, gemini_request_to_chat)
from app.routers.settings import get_output_protocol
from app.services.access_auth import verify_client_auth, verify_alias_client_key
import httpx

router = APIRouter(tags=["proxy"], dependencies=[Depends(verify_client_auth)])
alias_router = APIRouter(tags=["proxy-alias"])


def _instructions_of(chat_body: dict) -> str | None:
    """Recover the Responses `instructions` field from the converted chat body.

    `responses_request_to_chat` folds instructions into a leading system
    message; reading it back here avoids smuggling extra keys into the
    upstream request payload.
    """
    for msg in chat_body.get("messages", []):
        if msg.get("role") != "system":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content or None
        if isinstance(content, list):
            text = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
            return text or None
    return None


def _passthrough_usage(client_format: str, data: dict) -> tuple[int, int, int]:
    """Extract (prompt, completion, total) tokens from a native client-format body."""
    if client_format == "claude":
        usage = data.get("usage") or {}
        prompt = usage.get("input_tokens", 0) or 0
        completion = usage.get("output_tokens", 0) or 0
        return prompt, completion, prompt + completion
    if client_format == "gemini":
        meta = data.get("usageMetadata") or {}
        prompt = meta.get("promptTokenCount", 0) or 0
        completion = meta.get("candidatesTokenCount", 0) or 0
        return prompt, completion, meta.get("totalTokenCount", 0) or (prompt + completion)
    usage = data.get("usage") or {}
    prompt = usage.get("prompt_tokens", 0) or 0
    completion = usage.get("completion_tokens", 0) or 0
    return prompt, completion, usage.get("total_tokens", 0) or (prompt + completion)


def _passthrough_stream_usage(client_format: str, chunk_text: str) -> tuple[int, int]:
    """Best-effort token extraction from a raw upstream SSE frame / JSON line."""
    for line in chunk_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        payload = line[6:] if line.startswith("data: ") else line
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("type") == "message_delta":
            usage = obj.get("usage") or {}
            return (usage.get("input_tokens", 0) or 0), (usage.get("output_tokens", 0) or 0)
        if isinstance(obj, dict) and obj.get("type") == "message_start":
            usage = (obj.get("message") or {}).get("usage") or {}
            if usage:
                return (usage.get("input_tokens", 0) or 0), 0
        if isinstance(obj, dict) and obj.get("usageMetadata"):
            meta = obj["usageMetadata"]
            return (meta.get("promptTokenCount", 0) or 0), (meta.get("candidatesTokenCount", 0) or 0)
    return 0, 0


def _passthrough_error_event(message: str) -> str:
    """Emit an upstream error in the client's native wire format."""
    return "event: error\ndata: " + json.dumps({
        "type": "error",
        "error": {"type": "api_error", "message": message},
    }, ensure_ascii=False) + "\n\n"


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


#: 同一个 provider 内最多换几个 key（key 级故障转移上限）
MAX_KEY_ATTEMPTS = 3


async def _try_forward(strategy, db, request_body, is_stream, out_format="openai"):
    """Try to forward request using balancer with retry logic.

    两级故障转移：
    - rule 级：exclude_rule_ids 跳过失败的 provider/model 规则；
    - key 级：exclude_key_ids 跳过限流(429)/鉴权失败(401/403)的 key，换同 provider 的下一把。

    状态判定遵循「连不通 ≠ 弃用」：连接失败/DNS/超时、5xx、404 等只记录 last_error，
    key 状态保持不变；429 走冷却自动恢复；只有连续 401/403 才置inactive。
    """
    from app.utils.key_health import (
        classify_exception, classify_status_code, mark_failure, mark_success,
    )
    balancer = Balancer(db)
    forwarder = Forwarder(db)
    last_error = None
    last_rule = None
    last_provider = None
    last_model = None
    failed_rule_ids: set = set()
    failed_key_ids: set = set()
    log_prefix = f"[router] strategy={strategy.name}"

    for attempt in range(strategy.retry_count + 1):
        rule = await balancer.select_rule(strategy, exclude_rule_ids=failed_rule_ids)
        if not rule:
            last_error = "No active rules in strategy"
            print(f"{log_prefix} {last_error}", flush=True)
            raise HTTPException(503, detail=last_error)

        provider = await db.get(Provider, rule.provider_id)
        model = await db.get(Model, rule.model_id)
        if not provider or not model or not provider.is_active or not model.is_active:
            prov_name = provider.name if provider else f"id={rule.provider_id}"
            model_name = model.model_id if model else f"id={rule.model_id}"
            active_flags = ""
            if provider and not provider.is_active:
                active_flags += f" provider={prov_name}(inactive)"
            if model and not model.is_active:
                active_flags += f" model={model_name}(inactive)"
            if not provider:
                active_flags += f" provider_id={rule.provider_id}(not found)"
            if not model:
                active_flags += f" model_id={rule.model_id}(not found)"
            last_error = f"Provider or model unavailable:{active_flags}"
            last_rule = rule
            print(
                f"{log_prefix} attempt {attempt + 1}/{strategy.retry_count + 1}: "
                f"{last_error}",
                flush=True,
            )
            failed_rule_ids.add(rule.id)
            continue

        attempt_prefix = (
            f"{log_prefix} provider={provider.name} "
            f"model={model.model_id} stream={is_stream}"
        )
        last_rule, last_provider, last_model = rule, provider, model

        # --- key 级故障转移：同一 provider 内逐把尝试 ---
        rule_failed = False
        for key_try in range(MAX_KEY_ATTEMPTS):
            api_key = await balancer.select_key(
                provider.id, strategy, exclude_key_ids=failed_key_ids
            )
            if not api_key:
                last_error = f"No API key configured for {provider.name}"
                rule_failed = True
                break

            key_prefix = f"{attempt_prefix} key={api_key.alias or api_key.id}"
            try:
                # 成功即复位（连同 last_used_at 一起在 handler 内commit）
                mark_success(api_key)
                if is_stream:
                    return await _handle_stream(strategy, rule, provider, model, api_key, request_body, forwarder, db, out_format)
                return await _handle_non_stream(strategy, rule, provider, model, api_key, request_body, forwarder, db, out_format)
            except httpx.HTTPStatusError as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                kind = classify_status_code(status)
                last_error = f"HTTP {status}: {type(e).__name__}: {e}"
                failed_key_ids.add(api_key.id)
                try:
                    mark_failure(api_key, kind, f"HTTP {status}")
                    await db.commit()
                except Exception:
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                print(
                    f"{key_prefix} attempt {attempt + 1}/{strategy.retry_count + 1} "
                    f"HTTP {status} ({kind}, key #{api_key.id} 已跳过): {str(last_error)[:300]}",
                    flush=True,
                )
                if kind in ("rate_limit", "auth"):
                    continue  # key 级问题 → 换同 provider 的下一把 key
                rule_failed = True
                break  # 上游/配置问题 → 换 rule
            except httpx.RequestError as e:
                kind = classify_exception(e)  # 连不通：DNS/拒连/TLS/超时
                last_error = f"{type(e).__name__}: {e}"
                failed_key_ids.add(api_key.id)
                try:
                    mark_failure(api_key, kind, str(e)[:500])
                    await db.commit()
                except Exception:
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                print(
                    f"{key_prefix} attempt {attempt + 1}/{strategy.retry_count + 1} "
                    f"transport error ({kind}, key 状态不变): {str(last_error)[:300]}",
                    flush=True,
                )
                # 同一 host 连不通，换 key 也没用 → 直接换 rule
                rule_failed = True
                break
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                print(
                    f"{key_prefix} attempt {attempt + 1}/{strategy.retry_count + 1} "
                    f"non-retryable error: {str(last_error)[:300]}",
                    flush=True,
                )
                # 协议转换/响应处理类错误重试必然复现：记日志后立即原样抛出
                try:
                    await forwarder.log_request(
                        strategy.id, provider.id, api_key.id, model.model_id,
                        request_body, 500, 0, is_stream, str(last_error)[:500],
                    )
                except Exception:
                    pass
                raise

        if rule_failed:
            failed_rule_ids.add(rule.id)
            continue
        # 内层 key 用尽仍未成功 → 该 rule 视为失败，换下一条规则
        if last_error:
            print(
                f"{attempt_prefix} all keys failed, switching rule: {str(last_error)[:200]}",
                flush=True,
            )
        failed_rule_ids.add(rule.id)

    # --- 日志：console 兜底（即使 DB 写入失败也不丢失诊断信息）---
    model_name = last_model.model_id if last_model else "?"
    provider_name = last_provider.name if last_provider else "?"
    print(
        f"{log_prefix} ALL ATTEMPTS FAILED → 502  "
        f"provider={provider_name} model={model_name} "
        f"stream={is_stream} error={str(last_error)[:200]}",
        flush=True,
    )
    # --- 日志：写入 DB（失败不影响返回，仅 console 兜底已记录了诊断信息）---
    try:
        await forwarder.log_request(
            strategy.id,
            last_provider.id if last_provider else None,
            None,
            model_name,
            request_body, 502, 0, is_stream, str(last_error)[:500],
        )
    except Exception as log_exc:
        print(
            f"{log_prefix} WARNING: failed to write request log to DB: {log_exc}",
            flush=True,
        )

    raise HTTPException(502, detail=f"All attempts failed: {last_error}")


async def _handle_stream(strategy, rule, provider, model, api_key, request_body, forwarder, db, out_format="openai"):
    start = time.monotonic()

    token_counter = {"prompt": 0, "completion": 0}

    # 端点决定客户端格式（responses/claude/gemini）；openai 端点沿用全局设置兜底
    output_proto = get_output_protocol() if out_format == "openai" else out_format
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    writer = None
    if output_proto == "responses":
        writer = ResponsesStreamWriter(
            model_id=request_body.get("model") or model.model_id,
            instructions=_instructions_of(request_body),
            max_output_tokens=request_body.get("max_tokens"),
        )
    # 客户端格式与上游协议一致：forward_stream 原样吐出上游帧，直接下发
    passthrough = request_body.get("_raw_body") is not None and request_body.get("_client_format") == provider.protocol

    def _sse(events) -> str:
        return "".join(
            f"event: {etype}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            for etype, payload in events
        )

    async def generate():
        try:
            async for chunk in forwarder.forward_stream(strategy, rule, provider, model, api_key, request_body):
                if passthrough:
                    if chunk.strip():
                        p, c = _passthrough_stream_usage(request_body.get("_client_format"), chunk)
                        if p:
                            token_counter["prompt"] = p
                        if c:
                            token_counter["completion"] = c
                    yield chunk
                    continue
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
                if output_proto == "responses":
                    if chunk.strip() == "data: [DONE]":
                        continue
                    try:
                        import json as _json
                        obj = _json.loads(chunk[6:])
                    except Exception:
                        continue
                    events = writer.feed(obj)
                    if writer.finished:
                        # error / failed 之后不再收尾
                        yield _sse(events)
                        break
                    if events:
                        yield _sse(events)
                    continue
                if output_proto != "openai" and chunk.strip() == "data: [DONE]":
                    # 非 OpenAI 输出协议：不透传 OpenAI 的 [DONE] 终止符
                    continue
                if output_proto != "openai" and chunk.startswith("data: "):
                    # 非 OpenAI 输出协议：chunk 一律转换，无法转换的（如 reasoning）
                    # 直接丢弃，绝不把内部 chat chunk 泄漏给客户端
                    try:
                        import json as _json
                        obj = _json.loads(chunk[6:])
                    except Exception:
                        continue
                    if output_proto == "claude":
                        converted = convert_openai_stream_to_claude_chunks(obj, completion_id)
                    else:
                        converted = convert_openai_stream_to_gemini_chunks(obj)
                    if converted:
                        yield converted
                    continue
                yield chunk
            else:
                if output_proto == "responses" and not writer.finished and not passthrough:
                    yield _sse(writer.finish())
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
            print(
                f"[router] stream error (strategy={strategy.name} "
                f"provider={provider.name} model={model.model_id} "
                f"latency={latency}ms): {str(e)[:300]}",
                flush=True,
            )
            # 按失败原因更新 key 状态：连不通只记录、不弃用
            try:
                from app.utils.key_health import classify_exception, mark_failure
                mark_failure(api_key, classify_exception(e), str(e)[:500])
                await db.commit()
            except Exception:
                pass
            if output_proto == "responses" and not passthrough:
                try:
                    await forwarder.log_request(
                        strategy.id, provider.id, api_key.id, model.model_id,
                        request_body, 500, latency, True, str(e)[:500],
                    )
                except Exception as log_exc:
                    print(
                        f"[router] WARNING: failed to write stream error log: {log_exc}",
                        flush=True,
                    )
                yield _sse(writer.fail(str(e)[:200]))
                return
            if passthrough:
                # 保持客户端格式的错误信封
                try:
                    await forwarder.log_request(
                        strategy.id, provider.id, api_key.id, model.model_id,
                        request_body, 500, latency, True, str(e)[:500],
                    )
                except Exception:
                    pass
                yield _passthrough_error_event(str(e)[:200])
                return
            try:
                await forwarder.log_request(
                    strategy.id, provider.id, api_key.id, model.model_id,
                    request_body, 500, latency, True, str(e)[:500],
                )
            except Exception as log_exc:
                print(
                    f"[router] WARNING: failed to write stream error log: {log_exc}",
                    flush=True,
                )
            yield f"data: {json.dumps({'error': {'message': str(e)[:200]}})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _handle_non_stream(strategy, rule, provider, model, api_key, request_body, forwarder, db, out_format="openai"):
    start = time.monotonic()
    resp = await forwarder.forward(strategy, rule, provider, model, api_key, request_body, is_stream=False)
    latency = int((time.monotonic() - start) * 1000)

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    if resp.status_code >= 400:
        error_text = resp.text[:500]
        print(
            f"[router] upstream {resp.status_code} "
            f"(strategy={strategy.name} provider={provider.name} "
            f"model={model.model_id} latency={latency}ms): {error_text[:200]}",
            flush=True,
        )
        try:
            await forwarder.log_request(
                strategy.id, provider.id, api_key.id, model.model_id,
                request_body, resp.status_code, latency, False, error_text,
            )
        except Exception as log_exc:
            print(
                f"[router] WARNING: failed to write upstream error log: {log_exc}",
                flush=True,
            )
        if resp.status_code in (401, 403, 429):
            # 凭证被拒/限流属于 key 级问题：抛给上层换一把 key 再试
            resp.raise_for_status()
        output_proto = get_output_protocol() if out_format == "openai" else out_format
        if output_proto == "responses":
            return JSONResponse(
                status_code=resp.status_code,
                content={"error": {"message": error_text, "type": "upstream_error", "code": "upstream_error"}},
            )
        return JSONResponse(status_code=resp.status_code, content={"error": {"message": error_text}})

    data = resp.json()

    # 客户端格式与上游协议一致：上游响应即客户端所需格式，零转换直返
    passthrough = request_body.get("_raw_body") is not None and request_body.get("_client_format") == provider.protocol

    if not passthrough:
        if provider.protocol == "claude":
            data = claude_response_to_openai(data, model.model_id)
        elif provider.protocol == "gemini":
            data = gemini_response_to_openai(data, model.model_id)

    output_proto = get_output_protocol() if out_format == "openai" else out_format
    if not passthrough:
        if output_proto == "responses":
            data = chat_completion_to_response(
                data,
                request_body.get("model") or data.get("model") or model.model_id,
                instructions=_instructions_of(request_body),
                max_output_tokens=request_body.get("max_tokens"),
            )
        elif output_proto == "claude":
            data = openai_to_claude_response(data)
        elif output_proto == "gemini":
            data = openai_to_gemini_response(data)

    if passthrough:
        prompt_tok, completion_tok, total_tok = _passthrough_usage(
            request_body.get("_client_format"), data)
    else:
        usage = data.get("usage", {}) or {}
        if output_proto == "responses":
            prompt_tok = (usage.get("input_tokens", 0) or 0)
            completion_tok = (usage.get("output_tokens", 0) or 0)
            total_tok = usage.get("total_tokens", 0) or (prompt_tok + completion_tok)
        else:
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


async def _resolve_direct_model(model_name: str, db: AsyncSession):
    """Resolve a "provider_id/model_id" (or "provider_name/model_id") direct call.

    Returns (provider, model) or None when the name is not in direct form or
    nothing matches. Strategy names always win: this is only tried after the
    strategy lookup fails.
    """
    pid, sep, model_id = (model_name or "").partition("/")
    if not sep or not model_id:
        return None

    provider = None
    if pid.isdigit():
        provider = await db.get(Provider, int(pid))
    if provider is None:
        result = await db.execute(select(Provider).where(Provider.name == pid))
        provider = result.scalar_one_or_none()
    if not provider or not provider.is_active:
        return None

    result = await db.execute(
        select(Model).where(Model.provider_id == provider.id, Model.model_id == model_id, Model.is_active == True)
    )
    model_obj = result.scalar_one_or_none()
    if not model_obj:
        result = await db.execute(
            select(Model).where(Model.provider_id == provider.id, Model.display_name == model_id, Model.is_active == True)
        )
        model_obj = result.scalar_one_or_none()
    if not model_obj:
        return None
    return provider, model_obj


def _direct_pseudo_strategy(provider: Provider, model_obj: Model) -> Strategy:
    """Pseudo strategy for direct calls: key rotation follows the platform's
    own multi-key policy (Strategy settings stay authoritative for strategy
    routing)."""
    return Strategy(
        id=0, name=f"__direct__{provider.name}__{model_obj.model_id}",
        lb_strategy="round_robin", is_active=True,
        timeout=120, retry_count=0,
        key_strategy=getattr(provider, "key_strategy", None) or "round_robin",
        key_switch_mode=getattr(provider, "key_switch_mode", None) or "none",
        key_rpm_threshold=getattr(provider, "key_rpm_threshold", 0) or 0,
        key_count_threshold=getattr(provider, "key_count_threshold", 0) or 0,
    )


async def _mark_direct_key_error(api_key: ApiKey, status_code: int, db: AsyncSession):
    """Mirror _try_forward's key bookkeeping for direct calls."""
    if status_code == 429:
        api_key.status = "rate_limited"
        api_key.last_error = "Rate limited"
        await db.commit()
    elif status_code in (401, 403):
        api_key.status = "inactive"
        api_key.last_error = f"Auth error: {status_code}"
        await db.commit()


async def _forward_direct(provider: Provider, model_obj: Model, db: AsyncSession,
                          body: dict, is_stream: bool, out_format: str):
    """Forward a direct (provider/model) call, using the platform key policy."""
    balancer = Balancer(db)
    pseudo_strategy = _direct_pseudo_strategy(provider, model_obj)
    api_key = await balancer.select_key(provider.id, pseudo_strategy)
    if not api_key:
        raise HTTPException(503, detail=f"No active API key for provider {provider.name}")

    pseudo_rule = StrategyRule(
        id=0, strategy_id=0, provider_id=provider.id,
        model_id=model_obj.id, priority=1, weight=1, is_active=True,
    )
    pseudo_strategy.rules = [pseudo_rule]

    forwarder = Forwarder(db)
    if is_stream:
        return await _handle_stream(pseudo_strategy, pseudo_rule, provider, model_obj,
                                    api_key, body, forwarder, db, out_format)
    resp = await _handle_non_stream(pseudo_strategy, pseudo_rule, provider, model_obj,
                                    api_key, body, forwarder, db, out_format)
    if getattr(resp, "status_code", 200) >= 400:
        await _mark_direct_key_error(api_key, resp.status_code, db)
    return resp


async def _dispatch_by_model(model_name: str, db: AsyncSession, body: dict,
                             is_stream: bool, out_format: str):
    """Strategy routing first; fall back to 'provider_id/model_id' direct mode."""
    try:
        strategy = await _resolve(model_name, db)
    except HTTPException:
        direct = await _resolve_direct_model(model_name, db)
        if direct:
            return await _forward_direct(direct[0], direct[1], db, body, is_stream, out_format)
        if "/" in (model_name or ""):
            raise HTTPException(
                404,
                detail=f"Direct model '{model_name}' not found: check the provider id/name and the model id",
            )
        raise
    return await _try_forward(strategy, db, body, is_stream, out_format)


async def _chat_completions_impl(request: Request, db: AsyncSession, out_format="openai", body_override: dict | None = None):
    body = body_override if body_override is not None else await request.json()
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
        return await _forward_direct(provider, model_obj, db, body, is_stream, out_format)

    # Strategy routing first, then "provider_id/model_id" direct mode
    return await _dispatch_by_model(model_name, db, body, is_stream, out_format)


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, db: AsyncSession = Depends(get_db)):
    return await _chat_completions_impl(request, db)


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


async def _completions_impl(body: dict, db: AsyncSession, is_stream: bool, out_format: str = "openai"):
    """Legacy /v1/completions: same routing as chat completions."""
    prompt = body.get("prompt", "")
    model_name = body.get("model", "")
    chat_body = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": body.get("max_tokens", 1024),
        "stream": is_stream,
    }
    return await _dispatch_by_model(model_name, db, chat_body, is_stream, out_format)


# ============================================================
# OpenAI Responses API (POST /v1/responses)
# 入站请求/响应为 Responses 语义，内部复用 chat.completions 转发链路。
# 无状态：`store` / `previous_response_id` 不落库，由客户端自带完整历史。
# ============================================================

async def _responses_impl(request: Request, db: AsyncSession):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, detail="Request body must be a JSON object")
    chat_body = responses_request_to_chat(body)
    if not chat_body["messages"]:
        raise HTTPException(400, detail="'input' is required (string or non-empty array)")
    return await _chat_completions_impl(request, db, out_format="responses", body_override=chat_body)


@router.post("/v1/responses")
async def responses(request: Request, db: AsyncSession = Depends(get_db)):
    """OpenAI-compatible Responses API proxy (non-streaming and streaming)."""
    return await _responses_impl(request, db)


# ============================================================
# Anthropic Messages API (POST /v1/messages)
# 入站为 Claude 请求/响应语义；若上游同样是 claude 协议则原样透传。
# ============================================================

async def _messages_impl(request: Request, db: AsyncSession):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, detail="Request body must be a JSON object")
    chat_body = claude_request_to_chat(body)
    if not chat_body.get("messages"):
        raise HTTPException(400, detail="'messages' is required")
    if body.get("_direct_provider_id") is not None:
        chat_body["_direct_provider_id"] = body["_direct_provider_id"]
    chat_body["_client_format"] = "claude"
    chat_body["_raw_body"] = {k: v for k, v in body.items() if not k.startswith("_")}
    return await _chat_completions_impl(request, db, out_format="claude", body_override=chat_body)


@router.post("/v1/messages")
async def anthropic_messages(request: Request, db: AsyncSession = Depends(get_db)):
    """Anthropic-compatible Messages API proxy (same routing as chat completions)."""
    return await _messages_impl(request, db)


# ============================================================
# Google Gemini GenerateContent (POST /v1beta/models/{model}:{action})
# 路径与官方一致，Gemini 官方 SDK 只改 base_url 即可接入。
# 若上游同样是 gemini 协议则原样透传。
# ============================================================

def _split_gemini_path(rest: str) -> tuple[str, str]:
    """Split '/v1beta/models/{rest}' into (model, action).

    Model names may contain '/' (e.g. opencode/ling-3.1-flash-free), so the
    action is taken from the last ':' segment.
    """
    rest = (rest or "").strip("/")
    if ":" not in rest:
        raise HTTPException(404, detail="Not found. Use /v1beta/models/{model}:generateContent")
    model, _, action = rest.rpartition(":")
    model = model.strip("/")
    if not model or not action:
        raise HTTPException(404, detail="Not found. Use /v1beta/models/{model}:generateContent")
    return model, action


async def _gemini_impl(request: Request, db: AsyncSession, model: str, action: str):
    if action not in ("generateContent", "streamGenerateContent"):
        raise HTTPException(400, detail=f"Unsupported action '{action}'")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, detail="Request body must be a JSON object")
    model_name = (model or "").strip()
    if not model_name:
        raise HTTPException(400, detail="model is required in the URL path")
    chat_body = gemini_request_to_chat(body, model_name)
    if not chat_body.get("messages"):
        raise HTTPException(400, detail="'contents' is required")
    if action == "streamGenerateContent":
        chat_body["stream"] = True
    if body.get("_direct_provider_id") is not None:
        chat_body["_direct_provider_id"] = body["_direct_provider_id"]
    chat_body["_client_format"] = "gemini"
    chat_body["_raw_body"] = {k: v for k, v in body.items() if not k.startswith("_")}
    return await _chat_completions_impl(request, db, out_format="gemini", body_override=chat_body)


@router.post("/v1beta/models/{rest:path}")
async def gemini_generate(request: Request, rest: str,
                          db: AsyncSession = Depends(get_db)):
    """Gemini-compatible GenerateContent proxy (model = strategy name)."""
    model, action = _split_gemini_path(rest)
    return await _gemini_impl(request, db, model, action)


@router.get("/v1beta/models")
async def gemini_list_models(db: AsyncSession = Depends(get_db)):
    """Gemini-style model list (strategies as model names)."""
    return {
        "models": [
            {
                "name": f"models/{m['id']}",
                "id": m["id"],
                "object": "model",
                "displayName": m["id"],
                "supportedGenerationMethods": ["generateContent", "streamGenerateContent"],
            }
            for m in (await _models_impl(db))["data"]
        ],
    }


@alias_router.post("/k/{client_key}/v1/messages")
async def alias_messages(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _key: None = Depends(verify_alias_client_key),
):
    return await _messages_impl(request, db)


@alias_router.post("/k/{client_key}/v1beta/models/{rest:path}")
async def alias_gemini_generate(
    request: Request,
    client_key: str,
    rest: str,
    db: AsyncSession = Depends(get_db),
    _key: None = Depends(verify_alias_client_key),
):
    model, action = _split_gemini_path(rest)
    return await _gemini_impl(request, db, model, action)


@alias_router.get("/k/{client_key}/v1beta/models")
async def alias_gemini_list_models(
    client_key: str,
    db: AsyncSession = Depends(get_db),
    _key: None = Depends(verify_alias_client_key),
):
    return await gemini_list_models(db)


async def _models_impl(db: AsyncSession):
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


@router.get("/v1/models")
async def list_available_models(db: AsyncSession = Depends(get_db)):
    return await _models_impl(db)


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
    """Select an API key for a provider.

    优先取可用 key（active/untested，或限流已冷却）；
    一个可用都没有时回退到全部 key —— 不再因状态标记直接判定"无可用 key"。
    """
    from app.utils.key_health import is_usable, restore_due_keys

    await restore_due_keys(db, provider_id)
    result = await db.execute(
        select(ApiKey).where(ApiKey.provider_id == provider_id).order_by(ApiKey.id)
    )
    keys = list(result.scalars().all())
    if not keys:
        return None
    usable = [k for k in keys if is_usable(k.status, k.status_until)]
    return (usable or keys)[0]


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
# Embeddings Proxy
# ============================================================

async def _find_provider_and_model_for_embedding(model_name: str, provider_id: int | None, db: AsyncSession):
    """Resolve provider and model for embeddings."""
    if provider_id:
        provider = await db.get(Provider, int(provider_id))
        if not provider or not provider.is_active:
            raise HTTPException(404, detail=f"Provider '{provider_id}' not found or inactive")
        model_obj = await _resolve_model_from_provider(model_name, provider.id, db)
        if not model_obj:
            raise HTTPException(404, detail=f"Model '{model_name}' not found for provider {provider.name}")
        return provider, model_obj

    result = await db.execute(
        select(Model).where(Model.model_id == model_name, Model.model_type == "embedding", Model.is_active == True)
    )
    model_obj = result.scalars().first()
    if not model_obj:
        result2 = await db.execute(
            select(Model).where(Model.display_name == model_name, Model.model_type == "embedding", Model.is_active == True)
        )
        model_obj = result2.scalars().first()
    if not model_obj:
        raise HTTPException(404, detail=f"Embedding model '{model_name}' not found in any active provider")

    provider = await db.get(Provider, model_obj.provider_id)
    if not provider or not provider.is_active:
        raise HTTPException(404, detail=f"Provider for model '{model_name}' is not active")
    return provider, model_obj


@router.post("/v1/embeddings")
async def embeddings(request: Request, db: AsyncSession = Depends(get_db)):
    """OpenAI-compatible embeddings proxy (supports openai/custom and gemini upstreams)."""
    body = await request.json()
    model_name = body.pop("model", "")
    direct_provider_id = body.pop("_direct_provider_id", None)

    provider, model_obj = await _find_provider_and_model_for_embedding(
        model_name, int(direct_provider_id) if direct_provider_id else None, db
    )

    api_key = await _select_key_for_provider(provider.id, db)
    if not api_key:
        raise HTTPException(503, detail=f"No active API key for provider {provider.name}")

    raw_input = body.get("input", "")
    input_texts = [raw_input] if isinstance(raw_input, str) else [str(t) for t in raw_input]
    if not input_texts:
        raise HTTPException(400, detail="input must be a string or a list of strings")

    forwarder = Forwarder(db)
    start = time.time()
    try:
        vectors = await forwarder.forward_embeddings(provider, model_obj, api_key, input_texts)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(502, detail=f"Embedding request failed: {str(e)[:500]}")

    latency = int((time.time() - start) * 1000)
    try:
        await forwarder.log_request(
            0, provider.id, api_key.id, model_obj.model_id, {},
            200, latency, False, None,
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
        )
    except Exception:
        pass

    return {
        "object": "list",
        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)],
        "model": model_obj.model_id,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


# ============================================================
# Audio Transcription Proxy
# ============================================================

async def _find_provider_and_model_for_transcription(model_name: str, provider_id: int | None, db: AsyncSession):
    """Resolve provider and model for audio transcription (whisper-style models)."""
    if provider_id:
        provider = await db.get(Provider, int(provider_id))
        if not provider or not provider.is_active:
            raise HTTPException(404, detail=f"Provider '{provider_id}' not found or inactive")
        model_obj = await _resolve_model_from_provider(model_name, provider.id, db)
        if not model_obj:
            raise HTTPException(404, detail=f"Model '{model_name}' not found for provider {provider.name}")
        return provider, model_obj

    result = await db.execute(
        select(Model).where(Model.model_id == model_name, Model.model_type.in_(["tts", "audio"]), Model.is_active == True)
    )
    model_obj = result.scalars().first()
    if not model_obj:
        result2 = await db.execute(
            select(Model).where(Model.display_name == model_name, Model.model_type.in_(["tts", "audio"]), Model.is_active == True)
        )
        model_obj = result2.scalars().first()
    if not model_obj:
        raise HTTPException(404, detail=f"Transcription model '{model_name}' not found in any active provider")

    provider = await db.get(Provider, model_obj.provider_id)
    if not provider or not provider.is_active:
        raise HTTPException(404, detail=f"Provider for model '{model_name}' is not active")
    return provider, model_obj


@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(request: Request, db: AsyncSession = Depends(get_db)):
    """OpenAI-compatible audio transcription proxy (multipart: file + model)."""
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(400, detail="multipart field 'file' is required")
    model_name = str(form.get("model", ""))
    if not model_name:
        raise HTTPException(400, detail="model is required")

    direct_provider_id = form.get("_direct_provider_id")
    provider, model_obj = await _find_provider_and_model_for_transcription(
        model_name, int(direct_provider_id) if direct_provider_id else None, db
    )

    api_key = await _select_key_for_provider(provider.id, db)
    if not api_key:
        raise HTTPException(503, detail=f"No active API key for provider {provider.name}")

    file_bytes = await upload.read()
    fields = {}
    for key in ("language", "prompt", "response_format", "temperature"):
        if form.get(key) is not None:
            fields[key] = str(form.get(key))

    forwarder = Forwarder(db)
    try:
        result = await forwarder.forward_transcription(
            provider, model_obj, api_key,
            filename=upload.filename or "audio", file_bytes=file_bytes,
            content_type=upload.content_type or "audio/mpeg", fields=fields,
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(502, detail=f"Transcription failed: {str(e)[:500]}")

    return result


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

# ============================================================
# Key-in-path aliases (OmniRoute-style): for clients that cannot
# attach Authorization headers. The key itself is the credential.
# ============================================================

@alias_router.post("/k/{client_key}/v1/chat/completions")
async def alias_chat_completions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _key: None = Depends(verify_alias_client_key),
):
    return await _chat_completions_impl(request, db)


@alias_router.post("/k/{client_key}/v1/responses")
async def alias_responses(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _key: None = Depends(verify_alias_client_key),
):
    return await _responses_impl(request, db)


@alias_router.get("/k/{client_key}/v1/models")
async def alias_models(
    db: AsyncSession = Depends(get_db),
    _key: None = Depends(verify_alias_client_key),
):
    return await _models_impl(db)
