import time
import json
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.provider import Provider
from app.models.api_key import ApiKey
from app.models.model import Model
from app.models.strategy import Strategy, StrategyRule
from app.models.log import RequestLog
from app.utils.crypto import decrypt_value
from app.utils.protocol_adapter import (
    openai_to_claude, openai_to_gemini,
    claude_response_to_openai, gemini_response_to_openai,
)
import httpx


class Forwarder:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def forward(
        self, strategy: Strategy, rule: StrategyRule,
        provider: Provider, model: Model, api_key: ApiKey,
        request_body: dict, is_stream: bool,
    ) -> httpx.Response:
        real_key = decrypt_value(api_key.key_value)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")

        # Build upstream request based on protocol
        if protocol == "openai" or protocol == "custom":
            url = f"{base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            upstream_body = {**request_body, "model": model.model_id}
            if is_stream:
                upstream_body["stream"] = True

        elif protocol == "claude":
            url = f"{base_url}/messages"
            upstream_body, extra_headers = openai_to_claude(request_body)
            upstream_body["model"] = model.model_id
            headers = {
                "x-api-key": real_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                **extra_headers,
            }

        elif protocol == "gemini":
            method_action = "streamGenerateContent" if is_stream else "generateContent"
            url = f"{base_url}/models/{model.model_id}:{method_action}?key={real_key}"
            upstream_body, extra_headers = openai_to_gemini(request_body)
            upstream_body["model"] = model.model_id
            headers = {"content-type": "application/json", **extra_headers}

        else:
            raise ValueError(f"Unsupported protocol: {protocol}")

        timeout = strategy.timeout or 120
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=upstream_body)
            return resp

    async def forward_stream(
        self, strategy: Strategy, rule: StrategyRule,
        provider: Provider, model: Model, api_key: ApiKey,
        request_body: dict,
    ):
        """Yield SSE chunks from upstream, translated to OpenAI format."""
        real_key = decrypt_value(api_key.key_value)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")

        if protocol == "openai" or protocol == "custom":
            url = f"{base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            upstream_body = {**request_body, "model": model.model_id, "stream": True, "stream_options": {"include_usage": True}}

        elif protocol == "claude":
            url = f"{base_url}/messages"
            upstream_body, _ = openai_to_claude(request_body)
            upstream_body["model"] = model.model_id
            upstream_body["stream"] = True
            headers = {
                "x-api-key": real_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }

        elif protocol == "gemini":
            url = f"{base_url}/models/{model.model_id}:streamGenerateContent?key={real_key}"
            upstream_body, _ = openai_to_gemini(request_body)
            headers = {"content-type": "application/json"}
        else:
            raise ValueError(f"Unsupported protocol: {protocol}")

        timeout = strategy.timeout or 120
        completion_id = f"chatcmpl-{int(time.time()*1000)}"

        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream("POST", url, headers=headers, json=upstream_body) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise httpx.HTTPStatusError(
                        f"Upstream error {resp.status_code}", request=resp.request, response=resp
                    )

                if protocol == "openai" or protocol == "custom":
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                yield "data: [DONE]\n\n"
                                break
                            yield f"data: {data_str}\n\n"

                elif protocol == "claude":
                    import json as _json
                    current_event = ""
                    async for line in resp.aiter_lines():
                        if line.startswith("event: "):
                            current_event = line[7:].strip()
                        elif line.startswith("data: "):
                            data_str = line[6:].strip()
                            try:
                                chunk = _json.loads(data_str)
                                chunk["type"] = current_event
                                from app.utils.protocol_adapter import claude_stream_chunk_to_openai
                                openai_chunk = claude_stream_chunk_to_openai(chunk, model.model_id, completion_id)
                                if openai_chunk:
                                    yield f"data: {_json.dumps(openai_chunk)}\n\n"
                            except _json.JSONDecodeError:
                                pass

                elif protocol == "gemini":
                    import json as _json
                    buffer = ""
                    depth = 0
                    async for raw_line in resp.aiter_lines():
                        stripped = raw_line.strip()
                        if stripped == "[":
                            continue
                        if stripped == "]":
                            continue
                        if stripped.startswith("{"):
                            buffer = stripped
                            depth = stripped.count("{") - stripped.count("}")
                        elif buffer:
                            buffer += stripped
                            depth += stripped.count("{") - stripped.count("}")
                            if depth <= 0:
                                try:
                                    chunk = _json.loads(buffer)
                                    from app.utils.protocol_adapter import gemini_stream_chunk_to_openai
                                    openai_chunk = gemini_stream_chunk_to_openai(chunk, model.model_id, completion_id)
                                    if openai_chunk:
                                        yield f"data: {_json.dumps(openai_chunk)}\n\n"
                                except _json.JSONDecodeError:
                                    pass
                                buffer = ""
                                depth = 0

    async def send_test_request(self, strategy: Strategy, rule: StrategyRule) -> dict:
        from app.services.balancer import Balancer

        provider = await self.db.get(Provider, rule.provider_id)
        model = await self.db.get(Model, rule.model_id)
        if not provider or not model:
            return {"success": False, "message": "Provider or model not found"}

        balancer = Balancer(self.db)
        api_key = await balancer.select_key(provider.id)
        if not api_key:
            return {"success": False, "message": "No active API key"}

        test_body = {
            "model": "test",
            "messages": [{"role": "user", "content": "Say 'ok' in one word."}],
            "max_tokens": 10,
        }

        try:
            resp = await self.forward(strategy, rule, provider, model, api_key, test_body, is_stream=False)
            if 200 <= resp.status_code < 300:
                return {"success": True, "message": "Connection OK", "provider": provider.name, "model": model.model_id}
            else:
                return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"success": False, "message": str(e)[:200]}

    async def log_request(
        self, strategy_id: int, provider_id: int, api_key_id: int,
        model_used: str, request_body: dict, status_code: int,
        latency_ms: int, is_stream: bool, error_message: str | None,
        prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0,
    ):
        log = RequestLog(
            strategy_id=strategy_id,
            provider_id=provider_id,
            api_key_id=api_key_id,
            model_used=model_used,
            request_body=json.dumps(request_body)[:2000],
            status_code=status_code,
            latency_ms=latency_ms,
            is_stream=is_stream,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            error_message=error_message,
        )
        self.db.add(log)
        await self.db.commit()


    # ============================================================
    # Image Generation Forwarding
    # ============================================================

    async def forward_image(
        self, provider: Provider, model: Model, api_key: ApiKey,
        request_body: dict,
    ) -> httpx.Response:
        """Forward image generation request to the upstream provider."""
        real_key = decrypt_value(api_key.key_value)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")

        if protocol in ("openai", "custom"):
            url = f"{base_url}/images/generations"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            upstream_body = {**request_body, "model": model.model_id}

        elif protocol == "gemini":
            from app.utils.protocol_adapter import openai_image_to_gemini
            converted = openai_image_to_gemini({**request_body, "model": model.model_id})
            action = converted["action"]
            if action == "predict":
                # Imagen predict endpoint
                url = f"{base_url}/models/{model.model_id}:predict?key={real_key}"
                upstream_body = converted["body"]
            else:
                # Gemini native image gen via generateContent
                url = f"{base_url}/models/{model.model_id}:generateContent?key={real_key}"
                upstream_body = converted["body"]
            headers = {"Content-Type": "application/json"}

        elif protocol == "claude":
            raise ValueError("Anthropic does not support image generation")

        else:
            raise ValueError(f"Unsupported protocol for image generation: {protocol}")

        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=upstream_body)
            return resp

    # ============================================================
    # TTS Forwarding
    # ============================================================

    async def forward_tts(
        self, provider: Provider, model: Model, api_key: ApiKey,
        request_body: dict,
    ) -> tuple[httpx.Response, str]:
        """Forward TTS request. Returns (response, content_type).

        For OpenAI-like providers, the response is raw audio bytes.
        For Gemini, we extract audio from the generateContent response.
        """
        real_key = decrypt_value(api_key.key_value)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")

        if protocol in ("openai", "custom"):
            url = f"{base_url}/audio/speech"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            upstream_body = {**request_body, "model": model.model_id}
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                resp = await client.post(url, headers=headers, json=upstream_body)
                content_type = resp.headers.get("content-type", "audio/mpeg")
                return resp, content_type

        elif protocol == "gemini":
            from app.utils.protocol_adapter import openai_tts_to_gemini, gemini_tts_response_to_openai_audio
            gemini_body = openai_tts_to_gemini({**request_body, "model": model.model_id})
            url = f"{base_url}/models/{model.model_id}:generateContent?key={real_key}"
            headers = {"Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                resp = await client.post(url, headers=headers, json=gemini_body)
                if resp.status_code == 200:
                    audio_bytes = gemini_tts_response_to_openai_audio(resp.json())
                    if audio_bytes:
                        # Create a fake response with audio bytes
                        from starlette.responses import Response
                        # Return raw audio bytes and content_type
                        fake_resp = httpx.Response(
                            status_code=200,
                            content=audio_bytes,
                            headers={"content-type": "audio/wav"},
                        )
                        return fake_resp, "audio/wav"
                return resp, "application/json"

        elif protocol == "claude":
            raise ValueError("Anthropic does not support TTS")

        else:
            raise ValueError(f"Unsupported protocol for TTS: {protocol}")

    # ============================================================
    # Video Generation Forwarding
    # ============================================================

    async def forward_video(
        self, provider: Provider, model: Model, api_key: ApiKey,
        request_body: dict,
    ) -> httpx.Response:
        """Forward video generation request to the upstream provider."""
        real_key = decrypt_value(api_key.key_value)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")

        if protocol in ("openai", "custom"):
            url = f"{base_url}/videos"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            upstream_body = {**request_body, "model": model.model_id}

        elif protocol == "gemini":
            from app.utils.protocol_adapter import openai_video_request, video_request_to_gemini
            normalized = openai_video_request({**request_body, "model": model.model_id})
            # Veo models use :predict endpoint
            url = f"{base_url}/models/{model.model_id}:predict?key={real_key}"
            upstream_body = video_request_to_gemini(normalized)
            headers = {"Content-Type": "application/json"}

        elif protocol == "claude":
            raise ValueError("Anthropic does not support video generation")

        else:
            # For AgnesAi and other custom providers that follow OpenAI-like video API
            url = f"{base_url}/videos"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            upstream_body = {**request_body, "model": model.model_id}

        async with httpx.AsyncClient(timeout=300, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=upstream_body)
            return resp

    async def forward_video_get(
        self, provider: Provider, api_key: ApiKey,
        task_id: str,
    ) -> httpx.Response:
        """Retrieve video generation task status."""
        real_key = decrypt_value(api_key.key_value)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")

        if protocol in ("openai", "custom"):
            url = f"{base_url}/videos/{task_id}"
            headers = {"Authorization": f"Bearer {real_key}"}
        elif protocol == "gemini":
            url = f"{base_url}/operations/{task_id}?key={real_key}"
            headers = {}
        else:
            url = f"{base_url}/videos/{task_id}"
            headers = {"Authorization": f"Bearer {real_key}"}

        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.get(url, headers=headers)
            return resp