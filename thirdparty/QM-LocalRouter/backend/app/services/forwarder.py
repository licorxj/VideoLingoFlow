import time
import json
from typing import Any, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.provider import Provider
from app.models.api_key import ApiKey
from app.models.model import Model
from app.models.strategy import Strategy, StrategyRule
from app.models.log import RequestLog
from app.utils.crypto import decrypt_value
from app.utils import ssl_relax
from app.utils.protocol_adapter import (
    openai_to_claude, openai_to_gemini,
    claude_response_to_openai, gemini_response_to_openai,
)
import httpx

# LiteLLM 适配器导入 (延迟导入避免循环依赖)
_litellm_adapter = None
def _get_litellm_adapter():
    global _litellm_adapter
    if _litellm_adapter is None:
        from app.services.litellm_adapter import get_litellm_adapter
        _litellm_adapter = get_litellm_adapter()
    return _litellm_adapter


class Forwarder:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _post_json(self, url: str, headers: dict, body: dict, timeout: int) -> httpx.Response:
        return await ssl_relax.request_with_ssl_fallback(
            "POST", url, timeout=timeout, headers=headers, json=body
        )

    async def _real_key(self, api_key: ApiKey) -> str:
        """Decrypt the key, rotating OAuth access tokens that are about to expire."""
        if api_key.oauth_profile:
            from app.services import oauth_providers
            await oauth_providers.ensure_fresh_token(self.db, api_key)
        return decrypt_value(api_key.key_value)

    @staticmethod
    def _claude_auth_headers(real_key: str) -> dict:
        # OAuth tokens for Claude subscriptions authenticate with Bearer + the oauth beta header
        return {"Authorization": f"Bearer {real_key}", "anthropic-beta": "oauth-2025-04-20"}

    def _oauth_upstream(self, api_key: ApiKey) -> dict | None:
        """Profile 'upstream' config for OAuth/CLI-imported keys (auth headers, styles)."""
        if not api_key.oauth_profile:
            return None
        from app.services import oauth_providers, local_cli
        profile = oauth_providers.get_profile(api_key.oauth_profile) or {}
        upstream = dict(profile.get("upstream") or {})
        if not upstream:
            upstream = dict(local_cli.CLI_PLATFORMS.get(api_key.oauth_profile, {}).get("upstream") or {})
        upstream["profile_id"] = api_key.oauth_profile
        return upstream

    OPENCODE_FREE_MODELS = {"big-pickle", "deepseek-v4-flash-free", "mimo-v2.5-free",
                            "hy3-free", "nemotron-3-ultra-free", "north-mini-code-free"}

    def _opencode_keyless_gate(self, upstream: dict, real_key: str, model_id: str):
        """Keyless opencode connections may only call free-tier models (no auth header);
        premium models get a clear error instead of an upstream 401."""
        if upstream.get("profile_id") != "opencode" or real_key not in ("KEYLESS", "opencode-free"):
            return None
        if model_id.endswith("-free") or model_id in self.OPENCODE_FREE_MODELS:
            return {"skip_auth": True}
        raise ValueError("This model requires an opencode API key — use a '-free' model or import your Zen key (本地CLI 检测本机凭据)")

    @staticmethod
    def _apply_upstream_auth(headers: dict, upstream: dict, real_key: str) -> dict:
        """Apply the platform's auth scheme onto the headers dict."""
        auth = upstream.get("auth", "bearer")
        if auth == "none":
            headers.pop("Authorization", None)
        elif auth == "cloud-ide-jwt":
            headers["Authorization"] = f"Cloud-IDE-JWT {real_key}"
        elif auth == "bearer-workos":
            headers["Authorization"] = f"Bearer workos:{real_key}"
        elif auth == "bearer":
            headers["Authorization"] = f"Bearer {real_key}"
        return headers

    async def forward(
        self, strategy: Strategy, rule: StrategyRule,
        provider: Provider, model: Model, api_key: ApiKey,
        request_body: dict, is_stream: bool,
    ) -> httpx.Response:
        real_key = await self._real_key(api_key)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")
        upstream = self._oauth_upstream(api_key) or {}
        extra_headers = upstream.get("extra_headers") or {}
        responses_style = upstream.get("upstream_style") == "responses"

        # Build upstream request based on protocol
        if responses_style:
            # Codex OAuth upstream speaks the Responses API, not chat/completions
            from app.utils.protocol_adapter import chat_to_responses_request, responses_to_chat
            url = f"{base_url}/responses"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json", **extra_headers}
            resp = await self._post_json(url, headers, chat_to_responses_request(request_body, model.model_id),
                                         strategy.timeout or 120)
            if resp.status_code == 200:
                converted = responses_to_chat(resp.json(), model.model_id)
                from io import BytesIO
                return httpx.Response(status_code=200, content=json.dumps(converted).encode(),
                                      headers={"content-type": "application/json"})
            return resp

        if protocol == "openai" or protocol == "custom":
            keyless = self._opencode_keyless_gate(upstream, real_key, model.model_id)
            if upstream.get("auth") and upstream.get("auth") != "bearer":
                headers = self._apply_upstream_auth({"Content-Type": "application/json"}, upstream, real_key)
            else:
                headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            if keyless and keyless.get("skip_auth"):
                headers.pop("Authorization", None)
            headers.update(extra_headers)
            chat_path = upstream.get("chat_path") or "/chat/completions"
            url = f"{base_url}{chat_path}"
            upstream_body = {**request_body, "model": model.model_id}
            if is_stream:
                upstream_body["stream"] = True

        elif protocol == "claude":
            url = f"{base_url}/messages"
            upstream_body, extra_headers = openai_to_claude(request_body)
            upstream_body["model"] = model.model_id
            headers = {
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                **(self._claude_auth_headers(real_key) if api_key.oauth_profile else {"x-api-key": real_key}),
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
        # 主力聊天路径：证书 hostname 不匹配时按 host 降级重试（见 utils/ssl_relax）
        return await ssl_relax.request_with_ssl_fallback(
            "POST", url, timeout=timeout, headers=headers, json=upstream_body
        )

    async def forward_stream(
        self, strategy: Strategy, rule: StrategyRule,
        provider: Provider, model: Model, api_key: ApiKey,
        request_body: dict,
    ):
        """Yield SSE chunks from upstream, translated to OpenAI format."""
        real_key = await self._real_key(api_key)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")
        upstream = self._oauth_upstream(api_key) or {}
        extra_headers = upstream.get("extra_headers") or {}

        if upstream.get("upstream_style") == "responses":
            # Codex OAuth upstream: Responses API streaming -> OpenAI chunks
            from app.utils.protocol_adapter import chat_to_responses_request, responses_stream_chunk_to_chat
            url = f"{base_url}/responses"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json", **extra_headers}
            upstream_body = chat_to_responses_request({**request_body, "stream": True}, model.model_id)
            timeout = strategy.timeout or 120
            completion_id = f"chatcmpl-{int(time.time()*1000)}"

            async with ssl_relax.client(timeout, url) as client:
                async with client.stream("POST", url, headers=headers, json=upstream_body) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        raise httpx.HTTPStatusError(f"Upstream error {resp.status_code}", request=resp.request, response=resp)
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                            if data_str == "[DONE]":
                                yield 'data: [DONE]\n\n'
                                break
                            try:
                                event = json.loads(data_str)
                            except Exception:
                                continue
                            chunk = responses_stream_chunk_to_chat(event, model.model_id, completion_id)
                            if chunk:
                                yield 'data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n'
            return

        if protocol == "openai" or protocol == "custom":
            keyless = self._opencode_keyless_gate(upstream, real_key, model.model_id)
            if upstream.get("auth") and upstream.get("auth") != "bearer":
                headers = self._apply_upstream_auth({"Content-Type": "application/json"}, upstream, real_key)
            else:
                headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            if keyless and keyless.get("skip_auth"):
                headers.pop("Authorization", None)
            headers.update(extra_headers)
            chat_path = upstream.get("chat_path") or "/chat/completions"
            url = f"{base_url}{chat_path}"
            upstream_body = {**request_body, "model": model.model_id, "stream": True, "stream_options": {"include_usage": True}}

        elif protocol == "claude":
            url = f"{base_url}/messages"
            upstream_body, _ = openai_to_claude(request_body)
            upstream_body["model"] = model.model_id
            upstream_body["stream"] = True
            headers = {
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                **(self._claude_auth_headers(real_key) if api_key.oauth_profile else {"x-api-key": real_key}),
                **extra_headers,
            }

        elif protocol == "gemini":
            url = f"{base_url}/models/{model.model_id}:streamGenerateContent?key={real_key}"
            upstream_body, _ = openai_to_gemini(request_body)
            headers = {"content-type": "application/json"}
        else:
            raise ValueError(f"Unsupported protocol: {protocol}")

        timeout = strategy.timeout or 120
        completion_id = f"chatcmpl-{int(time.time()*1000)}"

        async with ssl_relax.client(timeout, url) as client:
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


    async def forward_embeddings(
        self, provider: Provider, model: Model, api_key: ApiKey,
        input_texts: list[str],
    ) -> list[list[float]]:
        """Return one embedding vector per input text."""
        real_key = decrypt_value(api_key.key_value)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")

        if protocol in ("openai", "custom"):
            url = f"{base_url}/embeddings"
            headers = {"Authorization": f"Bearer {real_key}", "Content-Type": "application/json"}
            upstream_body = {"model": model.model_id, "input": input_texts}
            async with ssl_relax.client(120, url) as client:
                resp = await client.post(url, headers=headers, json=upstream_body)
                if resp.status_code != 200:
                    raise ValueError(f"Upstream error {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                return [item["embedding"] for item in data.get("data", [])]

        elif protocol == "gemini":
            url = f"{base_url}/models/{model.model_id}:batchEmbedContents?key={real_key}"
            headers = {"Content-Type": "application/json"}
            upstream_body = {
                "requests": [
                    {"model": f"models/{model.model_id}", "content": {"parts": [{"text": t}]}}
                    for t in input_texts
                ]
            }
            async with ssl_relax.client(120, url) as client:
                resp = await client.post(url, headers=headers, json=upstream_body)
                if resp.status_code != 200:
                    raise ValueError(f"Upstream error {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                return [e["values"] for e in data.get("embeddings", [])]

        raise ValueError(f"Embeddings are not supported for protocol '{protocol}' (Claude has no embeddings API)")

    async def forward_transcription(
        self, provider: Provider, model: Model, api_key: ApiKey,
        filename: str, file_bytes: bytes, content_type: str, fields: dict,
    ) -> dict:
        """Forward an audio transcription request. Returns OpenAI-style {"text": ...}."""
        real_key = decrypt_value(api_key.key_value)
        protocol = provider.protocol
        base_url = provider.base_url.rstrip("/")

        if protocol in ("openai", "custom"):
            url = f"{base_url}/audio/transcriptions"
            headers = {"Authorization": f"Bearer {real_key}"}
            data = {**fields, "model": model.model_id}
            async with ssl_relax.client(120, url) as client:
                resp = await client.post(
                    url, headers=headers,
                    files={"file": (filename, file_bytes, content_type)},
                    data=data,
                )
                if resp.status_code != 200:
                    raise ValueError(f"Upstream error {resp.status_code}: {resp.text[:300]}")
                return resp.json()

        elif protocol == "gemini":
            # Audio understanding via generateContent with inline audio data
            import base64 as _b64
            mime = content_type or "audio/mpeg"
            url = f"{base_url}/models/{model.model_id}:generateContent?key={real_key}"
            headers = {"Content-Type": "application/json"}
            upstream_body = {
                "contents": [{
                    "parts": [
                        {"text": fields.get("prompt", "Transcribe this audio.")},
                        {"inline_data": {"mime_type": mime, "data": _b64.b64encode(file_bytes).decode()}},
                    ]
                }]
            }
            async with ssl_relax.client(120, url) as client:
                resp = await client.post(url, headers=headers, json=upstream_body)
                if resp.status_code != 200:
                    raise ValueError(f"Upstream error {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                return {"text": text}

        raise ValueError(f"Audio transcription is not supported for protocol '{protocol}' (Claude has no transcription API)")

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

        async with ssl_relax.client(120, url) as client:
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
            async with ssl_relax.client(120, url) as client:
                resp = await client.post(url, headers=headers, json=upstream_body)
                content_type = resp.headers.get("content-type", "audio/mpeg")
                return resp, content_type

        elif protocol == "gemini":
            from app.utils.protocol_adapter import openai_tts_to_gemini, gemini_tts_response_to_openai_audio
            gemini_body = openai_tts_to_gemini({**request_body, "model": model.model_id})
            url = f"{base_url}/models/{model.model_id}:generateContent?key={real_key}"
            headers = {"Content-Type": "application/json"}
            async with ssl_relax.client(120, url) as client:
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

        async with ssl_relax.client(300, url) as client:
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

        async with ssl_relax.client(30, url) as client:
            resp = await client.get(url, headers=headers)
            return resp

    # ============================================================
    # LiteLLM 转发方法
    # ============================================================

    async def forward_with_litellm(
        self,
        provider: Provider,
        model: Model,
        api_key: ApiKey,
        request_body: dict,
        is_stream: bool = False,
        timeout: int = 120,
    ) -> Any:
        """
        使用 LiteLLM 转发请求到上游提供商

        Args:
            provider: 提供商
            model: 模型
            api_key: API 密钥
            request_body: 请求体 (OpenAI 格式)
            is_stream: 是否流式
            timeout: 超时秒数

        Returns:
            litellm 响应对象
        """
        adapter = _get_litellm_adapter()

        # 构建模型配置
        config = adapter.build_model_config(provider, model, api_key)

        # 提取消息
        messages = request_body.get("messages", [])

        # 构建 litellm 请求参数
        params = {
            "model": config.litellm_model,
            "messages": messages,
            "stream": is_stream,
        }

        # 添加可选参数
        for param in ["temperature", "max_tokens", "top_p", "frequency_penalty",
                      "presence_penalty", "stop", "response_format", "tools",
                      "tool_choice", "seed"]:
            if param in request_body:
                params[param] = request_body[param]

        # 如果有自定义 api_base
        if config.api_base:
            params["api_base"] = config.api_base

        # 调用 litellm
        return await adapter.completion(**params, timeout=timeout)

    async def forward_stream_with_litellm(
        self,
        provider: Provider,
        model: Model,
        api_key: ApiKey,
        request_body: dict,
        timeout: int = 120,
    ) -> AsyncGenerator[str, None]:
        """
        使用 LiteLLM 转发流式请求

        Yields:
            SSE 格式的数据块
        """
        adapter = _get_litellm_adapter()
        config = adapter.build_model_config(provider, model, api_key)

        messages = request_body.get("messages", [])

        params = {
            "model": config.litellm_model,
            "messages": messages,
        }

        for param in ["temperature", "max_tokens", "top_p", "frequency_penalty",
                      "presence_penalty", "stop", "response_format", "tools",
                      "tool_choice", "seed"]:
            if param in request_body:
                params[param] = request_body[param]

        if config.api_base:
            params["api_base"] = config.api_base

        async for chunk in adapter.completion_stream(**params, timeout=timeout):
            yield chunk

    async def multi_forward_litellm(
        self,
        targets: list[dict],
        messages: list,
        timeout: int = 120,
    ) -> list[dict]:
        """
        同时向多个端点发送请求 (使用 LiteLLM)

        Args:
            targets: 目标列表，每项包含 provider, model, api_key
            messages: 消息列表
            timeout: 超时秒数

        Returns:
            所有响应的列表
        """
        adapter = _get_litellm_adapter()

        requests = []
        for target in targets:
            provider = target["provider"]
            model = target["model"]
            api_key = target["api_key"]

            config = adapter.build_model_config(provider, model, api_key)

            req = {
                "model": config.litellm_model,
                "messages": messages,
            }

            if config.api_base:
                req["api_base"] = config.api_base

            requests.append(req)

        return await adapter.multi_forward(requests, timeout)
