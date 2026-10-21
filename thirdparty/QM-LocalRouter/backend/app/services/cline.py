"""Cline（cline.bot）白嫖模型的转发客户端（移植自 licorxj/cline2api-workers）。

Cline 不是标准 OpenAI 端点，必须按官方插件的私有协议通信，否则免费模型直接 403/500：

- 真实端点：POST https://api.cline.bot/api/v1/chat/completions
- 认证：Authorization: Bearer workos:<accessToken>（accessToken 由 refresh 换得）
- 必须带 Cline 客户端指纹头（User-Agent / X-CLIENT-TYPE / X-PLATFORM / X-CORE-VERSION ...），
  否则免费模型返回 403 ``only available via Cline product surfaces``
- 请求体带 ``max_tokens`` 字段 → 免费模型一律 500 ``empty response content``，必须剥离
- 免费通道（deepseek/ / cline-free/ / cline-pass/）非流式被限流 500，需强制上游走 stream 再聚合
- 响应有时包一层 {data:{...}}，需 unwrap
"""
import json
import time
import uuid

import httpx

CLINE_API_BASE = "https://api.cline.bot/api/v1"
DEFAULT_MODEL = "cline-free/deepseek-v4.1-flash"

# 强制上游走 stream 再聚合的模型前缀（免费通道非流式被限流）
_FORCE_STREAM_PREFIXES = ("deepseek/", "cline-free/", "cline-pass/")

# 免费模型白名单（动态拉取失败时回退，2026-08-29 口径）
_FREE_WHITELIST = [
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-flash-0731",
    "z-ai/glm-5.3-flash",
    "z-ai/glm-5.2:free",
    "xiaomi/mimo-v2.5",
    "minimax/minimax-m3",
    "poolside/laguna-s-2.1",
    "cline-free/deepseek-v4.1-flash",
    "cline-free/muse-spark-1.3-contributor",
    "cline-free/solar-pro4",
]


class ClineError(Exception):
    def __init__(self, status: int, message: str, code: str = "upstream_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def _session_id() -> str:
    return "sess_" + _short_id()


def _unwrap(obj):
    """剥掉上游偶尔的 {data:{...}} 包装（只当 data 里像 chat.completion 时才剥）。"""
    if isinstance(obj, dict) and isinstance(obj.get("data"), dict):
        d = obj["data"]
        if d.get("choices") or d.get("id") or d.get("usage"):
            return d
    return obj


class ClineClient:
    def __init__(self, base_url: str = CLINE_API_BASE, access_token: str = "", timeout: float = 600):
        self.base_url = (base_url or CLINE_API_BASE).rstrip("/")
        self.access_token = access_token or ""
        self.timeout = timeout

    # ----------------------------------------------------------- 指纹请求头
    def _headers(self, session_id: str) -> dict:
        return {
            "Authorization": f"Bearer workos:{self.access_token}",
            "Content-Type": "application/json",
            "User-Agent": "Cline/3.0.47",
            "HTTP-Referer": "https://cline.bot",
            "X-Title": "Cline",
            "X-IS-MULTIROOT": "false",
            "X-CLIENT-TYPE": "cline-sdk",
            "X-CLIENT-VERSION": "3.0.47",
            "X-PLATFORM": "terminal",
            "X-PLATFORM-VERSION": "3.0.47",
            "X-CORE-VERSION": "0.0.66",
            "X-Task-ID": session_id,
        }

    # ----------------------------------------------------------- 健康检查/目录
    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                r = await client.get(self.base_url + "/models",
                                     headers={"User-Agent": "Mozilla/5.0 (cline2api)"})
            return r.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        models: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                r = await client.get(self.base_url + "/models",
                                     headers={"User-Agent": "Mozilla/5.0 (cline2api)"})
                if r.status_code == 200:
                    data = r.json()
                    for m in data.get("data", []):
                        mid = m.get("id")
                        if not mid or mid.endswith(":batch"):
                            continue
                        if mid.endswith(":free") or mid in _FREE_WHITELIST:
                            models.append({"id": mid, "owned_by": "cline"})
        except Exception:
            pass
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                r = await client.get(self.base_url + "/ai/cline/recommended-models",
                                     headers={"User-Agent": "Mozilla/5.0 (cline2api)"})
                if r.status_code == 200:
                    for m in (r.json().get("free") or []):
                        mid = m.get("id")
                        if mid and not any(x["id"] == mid for x in models):
                            models.append({"id": mid, "owned_by": "cline"})
        except Exception:
            pass
        for m in models:
            m["object"] = "model"
            m["created"] = 1704067200
            m["name"] = m["id"]
        return models

    # ----------------------------------------------------------- 请求体构造
    def _build_body(self, messages, model_id, *, stream, temperature=None,
                    reasoning_effort=None, extra=None) -> dict:
        body = {
            "model": model_id,
            "session_id": _session_id(),
            "reasoning_effort": reasoning_effort or "high",
            "messages": messages,
        }
        if extra:
            for k in ("temperature", "top_p", "tools", "tool_choice", "stop",
                      "presence_penalty", "frequency_penalty", "response_format",
                      "user", "n", "seed"):
                if k in extra and extra[k] is not None:
                    body[k] = extra[k]
        if temperature is not None:
            body["temperature"] = temperature
        if stream:
            body["stream"] = True
        # 重要：上游风控——免费模型请求体带 max_tokens 一律 500，客户端传了也剥离
        body.pop("max_tokens", None)
        body.pop("max_completion_tokens", None)
        return body

    async def _post(self, path: str, body: dict, session_id: str) -> httpx.Response:
        url = self.base_url + path
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                resp = await client.post(url, headers=self._headers(session_id), json=body)
        except httpx.TimeoutException:
            raise ClineError(504, "Cline 上游超时", "timeout")
        except httpx.HTTPError as e:
            raise ClineError(502, f"无法连接 Cline 上游: {e}", "connection_error")
        return resp

    # ----------------------------------------------------------- 非流式聚合
    async def chat_completion(self, messages, model_id, *, stream=False,
                             temperature=None, reasoning_effort=None, extra=None) -> dict:
        force_stream = (not stream) and any(
            model_id.startswith(p) for p in _FORCE_STREAM_PREFIXES)
        body = self._build_body(messages, model_id, stream=stream or force_stream,
                                temperature=temperature, reasoning_effort=reasoning_effort,
                                extra=extra)
        sid = body["session_id"]
        resp = await self._post("/chat/completions", body, sid)
        if resp.status_code >= 400:
            text = resp.text[:300] or f"HTTP {resp.status_code}"
            raise ClineError(resp.status_code, f"Cline 上游错误: {text}", "upstream_error")
        ct = resp.headers.get("content-type") or ""
        if "text/event-stream" in ct or stream or force_stream:
            return await self._aggregate_sse(resp, model_id)
        # 非流式 JSON（非免费通道）
        try:
            data = _unwrap(resp.json())
        except ValueError:
            raise ClineError(502, "Cline 返回非 JSON", "invalid_upstream")
        return self._normalize_completion(data, model_id)

    # ----------------------------------------------------------- 流式透传
    async def stream_chunks(self, messages, model_id, *, temperature=None,
                           reasoning_effort=None, extra=None):
        body = self._build_body(messages, model_id, stream=True,
                                temperature=temperature, reasoning_effort=reasoning_effort,
                                extra=extra)
        sid = body["session_id"]
        resp = await self._post("/chat/completions", body, sid)
        if resp.status_code >= 400:
            text = resp.text[:300] or f"HTTP {resp.status_code}"
            raise ClineError(resp.status_code, f"Cline 上游错误: {text}", "upstream_error")
        completion_id = "chatcmpl-" + _short_id()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            obj = _unwrap(obj)
            if isinstance(obj, dict):
                obj["model"] = model_id
                yield obj

    # ----------------------------------------------------------- SSE 聚合
    async def _aggregate_sse(self, resp: httpx.Response, model_id: str) -> dict:
        content, reasoning = "", ""
        tool_calls: dict[int, dict] = {}
        finish_reason = None
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            obj = _unwrap(obj)
            choice = (obj.get("choices") or [{}])[0]
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            if isinstance(delta.get("content"), str):
                content += delta["content"]
            if isinstance(delta.get("reasoning"), str):
                reasoning += delta["reasoning"]
            for tc in (delta.get("tool_calls") or []):
                if not isinstance(tc, dict):
                    continue
                idx = tc.get("index", 0)
                slot = tool_calls.setdefault(idx, {"index": idx, "id": "", "type": "function",
                                                  "function": {"name": "", "arguments": ""}})
                fn = tc.get("function") or {}
                if tc.get("id"):
                    slot["id"] = tc["id"]
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
        msg: dict = {"role": "assistant", "content": content or None}
        if reasoning:
            msg["reasoning_content"] = reasoning
        if tool_calls:
            msg["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]
        if not content and reasoning:
            # 兜底：免费通道偶发整条只有 reasoning，拼回去保证客户端可见
            msg["content"] = reasoning
            msg.pop("reasoning_content", None)
        return {
            "id": "chatcmpl-" + _short_id(),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_id,
            "choices": [{
                "index": 0,
                "message": msg,
                "finish_reason": finish_reason or "stop",
                "logprobs": None,
                "native_finish_reason": finish_reason or "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @staticmethod
    def _normalize_completion(data: dict, model_id: str) -> dict:
        choices = []
        for ch in (data.get("choices") or []):
            msg = ch.get("message") or {}
            if "reasoning" in msg and "reasoning_content" not in msg:
                msg["reasoning_content"] = msg.pop("reasoning")
            choices.append(ch)
        return {
            "id": data.get("id", "chatcmpl-" + _short_id()),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_id,
            "choices": choices,
            "usage": data.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
