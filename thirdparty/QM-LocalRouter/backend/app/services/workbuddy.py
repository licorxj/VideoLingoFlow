"""WorkBuddy / CodeBuddy 上游调用（移植自 yxxawa/workbuddy_to_api 的 wb_gateway）。

凭据沿用本项目 ApiKey 结构存放：
- key_value        : 加密后的 access token
- oauth_refresh    : 加密后的 JSON blob（refresh_token / uid / enterprise_id / department / region / expires_at ...）
- oauth_expires_at : unix 秒

上游接口（与官方插件一致）：
- POST /v2/plugin/auth/state?platform=...  -> 登录 state + authUrl
- GET  /v2/plugin/auth/token?state=...     -> accessToken / refreshToken（11217 = 待用户确认）
- GET  /v2/plugin/login/account?state=...  -> 账号资料（12151 = 待用户确认）
- POST /v2/plugin/auth/token/refresh       -> 刷新令牌（X-Refresh-Token 头）
- GET  /v3/config                          -> 模型目录
- POST /v2/chat/completions                -> 对话（上游始终 SSE 流式）
"""
import copy
import json
import os
import time
import urllib.parse
import uuid

import httpx

# ------------------------------------------------------------------ 区域配置

REGIONS = {
    "cn": {
        "endpoint": "https://www.workbuddy.cn",
        "platform": "workbuddy",
        "version": "5.6.2",
        "application_name": "WorkBuddy",
    },
    "intl": {
        "endpoint": "https://www.workbuddy.ai",
        "platform": "workbuddy-ai",
        "version": "5.6.2",
        "application_name": "workbuddy-ai",
    },
}

ALLOWED_HOSTS = {
    "www.workbuddy.cn", "www.workbuddy.ai",
    "www.codebuddy.cn", "www.codebuddy.ai",
    "copilot.tencent.com",
}

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Follow the user instructions "
    "and use only the tools explicitly provided."
)

PENDING_TOKEN_CODES = ("11217", "12151")


class WorkBuddyError(Exception):
    def __init__(self, status: int, message: str, code: str = "upstream_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def normalize_region(region: str) -> str:
    """cn / intl 互转，兼容 gl、global 等写法。"""
    value = (region or "").strip().lower()
    if value in ("intl", "gl", "global", "international", "overseas"):
        return "intl"
    return "cn"


def public_region(region: str) -> str:
    return "gl" if normalize_region(region) == "intl" else "cn"


def strip_model_prefix(model: str) -> tuple[str | None, str]:
    """'cn/xxx' -> ('cn', 'xxx')；无前缀 -> (None, 原名)。"""
    text = model or ""
    prefix, sep, rest = text.partition("/")
    if sep and prefix in ("cn", "gl", "intl"):
        return normalize_region(prefix), rest
    return None, text


def _config(region: str) -> dict:
    region = normalize_region(region)
    cfg = dict(REGIONS[region])
    override = os.environ.get("WB_ENDPOINT_CN" if region == "cn" else "WB_ENDPOINT_INTL")
    if override:
        cfg["endpoint"] = override.strip().rstrip("/")
    return cfg


def _host_allowed(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in ALLOWED_HOSTS


# ------------------------------------------------------------------ 请求头

def _headers(region: str, credential: dict | None = None, anonymous: bool = False) -> dict:
    cfg = _config(region)
    app = cfg["application_name"]
    version = cfg["version"]
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Product": "SaaS",
        "X-Requested-With": "XMLHttpRequest",
        "X-Domain": urllib.parse.urlsplit(cfg["endpoint"]).netloc,
        "X-IDE-Type": app,
        "X-IDE-Name": app,
        "X-IDE-Version": version,
        "X-Product-Version": version,
        "X-Request-ID": "req_" + uuid.uuid4().hex,
        "User-Agent": f"CLI/unknown {app}/{version} LocalRouter/1.0",
    }
    if anonymous:
        for key in ("X-No-Authorization", "X-No-User-Id", "X-No-Enterprise-Id", "X-No-Department-Info"):
            headers[key] = "true"
        return headers
    credential = credential or {}
    token = credential.get("access_token") or ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if credential.get("domain"):
        headers["X-Domain"] = str(credential["domain"])
    # 官方网关要求账号维度信息放在独立头里
    if credential.get("uid") not in (None, ""):
        headers["X-User-Id"] = urllib.parse.quote(str(credential["uid"]), safe="")
    if credential.get("enterprise_id") not in (None, ""):
        headers["X-Enterprise-Id"] = urllib.parse.quote(str(credential["enterprise_id"]), safe="")
    if credential.get("department"):
        headers["X-Department-Info"] = urllib.parse.quote(str(credential["department"]), safe="")
    return headers


def _error_text(raw: bytes, status: int) -> str:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return (raw.decode("utf-8", "replace") if raw else f"HTTP {status}")[:500]
    err = data.get("error") if isinstance(data.get("error"), dict) else data
    if not isinstance(err, dict):
        return f"HTTP {status}"
    return str(err.get("message") or err.get("msg") or f"HTTP {status}")[:500]


# ------------------------------------------------------------------ 通用调用

async def call(
    region: str, path: str, credential: dict | None = None,
    method: str = "GET", body: dict | None = None, headers: dict | None = None,
    anonymous: bool = False, timeout: float = 30, raw_codes: tuple = (),
) -> dict | list:
    """调用官方接口，返回解包后的 data。raw_codes 中的业务码原样返回（用于轮询）。"""
    cfg = _config(region)
    url = cfg["endpoint"].rstrip("/") + path
    merged = {**_headers(region, credential, anonymous), **(headers or {})}
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.request(method, url, json=body, headers=merged)
    except httpx.TimeoutException:
        raise WorkBuddyError(504, "Upstream timeout", "upstream_timeout")
    except httpx.HTTPError:
        raise WorkBuddyError(502, "Upstream connection failed", "upstream_connection_error")

    try:
        data = resp.json()
    except ValueError:
        data = {"error": {"code": "invalid_upstream", "message": "Upstream returned non-JSON"}}
    if not isinstance(data, dict):
        raise WorkBuddyError(502, "Invalid upstream body", "invalid_upstream")

    bad = (
        not 200 <= resp.status_code < 300
        or data.get("error")
        or data.get("code") not in (None, 0, 200, "0", "200")
    )
    if bad:
        if str(data.get("code")) in raw_codes:
            return data
        err = data.get("error") if isinstance(data.get("error"), dict) else data
        message = str(err.get("message") or err.get("msg") or "Official API rejected request")
        status = resp.status_code if 400 <= resp.status_code < 500 else 502
        raise WorkBuddyError(status, message[:500], "upstream_" + str(err.get("code", "error")))
    return data.get("data", data)


# ------------------------------------------------------------------ 登录流程

async def start_login(region: str = "cn") -> dict:
    """第一步：向官方申请登录 state 与授权页 URL。"""
    region = normalize_region(region)
    cfg = _config(region)
    path = "/v2/plugin/auth/state?platform=" + urllib.parse.quote(cfg["platform"])
    data = await call(region, path, method="POST", body={}, anonymous=True)
    state = data.get("state")
    auth_url = data.get("authUrl")
    if not isinstance(state, str) or not isinstance(auth_url, str):
        raise WorkBuddyError(502, "Invalid login state", "invalid_login_state")
    if not _host_allowed(auth_url):
        raise WorkBuddyError(502, "Untrusted authorization URL", "untrusted_auth_url")
    parts = urllib.parse.urlsplit(auth_url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query["version"] = cfg["version"]
    auth_url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    return {"region": region, "state": state, "auth_url": auth_url}


async def poll_login(region: str, state: str) -> dict:
    """第二步：轮询授权结果。返回 {"status": "pending"|"complete", ...}。"""
    region = normalize_region(region)
    suffix = "?state=" + urllib.parse.quote(state or "")

    token = await call(region, "/v2/plugin/auth/token" + suffix, anonymous=True,
                       raw_codes=PENDING_TOKEN_CODES)
    if str(token.get("code")) in PENDING_TOKEN_CODES or not token.get("accessToken"):
        return {"status": "pending"}

    credential = {
        "region": region,
        "access_token": token["accessToken"],
        "refresh_token": token.get("refreshToken", ""),
    }
    now_ms = int(time.time() * 1000)
    if isinstance(token.get("expiresIn"), (int, float)):
        credential["expires_at"] = now_ms + int(token["expiresIn"]) * 1000
    if isinstance(token.get("refreshExpiresIn"), (int, float)):
        credential["refresh_expires_at"] = now_ms + int(token["refreshExpiresIn"]) * 1000

    account = await call(region, "/v2/plugin/login/account" + suffix, credential=credential,
                         raw_codes=PENDING_TOKEN_CODES)
    if str(account.get("code")) in PENDING_TOKEN_CODES or not account.get("uid"):
        return {"status": "pending"}

    credential.update({
        "uid": account.get("uid"),
        "nickname": account.get("nickname", ""),
        "enterprise_id": account.get("enterpriseId") or "",
        "department": account.get("departmentFullName") or "",
        "account_type": account.get("type", ""),
    })
    return {"status": "complete", "region": region, "credential": credential, "account": account}


async def refresh_credential(region: str, credential: dict) -> dict:
    """用 refresh_token 换新 access token，并顺带同步账号资料。"""
    region = normalize_region(region)
    cur = dict(credential or {})
    if not cur.get("refresh_token"):
        raise WorkBuddyError(401, "Session expired; log in again", "login_required")
    data = await call(
        region, "/v2/plugin/auth/token/refresh", cur, method="POST", body={},
        headers={"X-Refresh-Token": str(cur["refresh_token"]), "X-Auth-Refresh-Source": "plugin"},
    )
    if not data.get("accessToken"):
        raise WorkBuddyError(502, "Upstream refresh returned no access token", "upstream_error")
    out = dict(cur)
    out["access_token"] = data["accessToken"]
    if data.get("refreshToken"):
        out["refresh_token"] = data["refreshToken"]
    now_ms = int(time.time() * 1000)
    if isinstance(data.get("expiresIn"), (int, float)):
        out["expires_at"] = now_ms + int(data["expiresIn"]) * 1000
    if isinstance(data.get("refreshExpiresIn"), (int, float)):
        out["refresh_expires_at"] = now_ms + int(data["refreshExpiresIn"]) * 1000

    # 账号资料同步失败不影响本次刷新
    try:
        rows = await call(region, "/v2/plugin/accounts", out)
        rows = rows if isinstance(rows, list) else (rows.get("accounts") or [])
        uid = cur.get("uid")
        account = None
        if uid is not None:
            account = next((x for x in rows if str(x.get("uid")) == str(uid)), None)
        if account is None and rows:
            account = next((x for x in rows if x.get("lastLogin")), None) or rows[0]
        if isinstance(account, dict):
            for src, dst in (("uid", "uid"), ("nickname", "nickname"),
                             ("enterpriseId", "enterprise_id"),
                             ("departmentFullName", "department")):
                if account.get(src) not in (None, ""):
                    out[dst] = account[src]
    except WorkBuddyError:
        pass
    return out


# ------------------------------------------------------------------ 模型目录

def visible_models(product: dict) -> list[dict]:
    """从 /v3/config 的 product 配置里挑出官方可对话的模型。"""
    agents = product.get("agents") or []
    agent = (
        next((a for a in agents if a.get("name") == "craft"), None)
        or next((a for a in agents if "default" in (a.get("tags") or [])), None)
        or next((a for a in agents if a.get("name") == "cli"), None)
    )
    available = set(product.get("availableModels") or [])
    ids = set(agent["models"]) if agent and isinstance(agent.get("models"), list) else available
    if not ids:
        raise WorkBuddyError(503, "Official chat model visibility unavailable", "catalog_visibility_unavailable")
    excluded = {"text-to-image", "text-to-video", "image-to-video"}
    out: dict[str, dict] = {}
    for m in product.get("models") or []:
        mid = m.get("id")
        if not isinstance(mid, str) or mid not in ids:
            continue
        if available and mid not in available:
            continue
        if m.get("local") or m.get("url") or m.get("disabled") or m.get("hidden"):
            continue
        if m.get("enabled") is False:
            continue
        if excluded.intersection(m.get("tags") or []):
            continue
        out.setdefault(mid, m)
    return list(out.values())


def model_controls(m: dict) -> dict:
    reasoning = m.get("reasoning") or {}
    allowed = {"minimal", "low", "medium", "high", "xhigh", "max"}
    efforts = [e for e in (reasoning.get("supportedEfforts") or []) if e in allowed]
    window = m.get("contextWindow") or {}
    max_input = m.get("maxInputTokens")
    limit = max_input if isinstance(max_input, (int, float)) else float("inf")
    lengths = sorted({
        x for x in (window.get("supportedLengths") or [])
        if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 < x <= limit
    })
    return {
        "supports_reasoning": bool(m.get("supportsReasoning")),
        "efforts": efforts,
        "context_lengths": lengths,
        "max_input_tokens": max_input,
        "max_output_tokens": m.get("maxOutputTokens"),
        "supports_tools": bool(m.get("supportsToolCall")),
        "supports_images": bool(m.get("supportsImages")),
    }


def catalog_models(region: str, product: dict) -> list[dict]:
    """模型目录 -> 本项目可直接落库的模型条目（带 cn/ gl/ 区域前缀）。"""
    region = normalize_region(region)
    prefix = public_region(region)
    items = []
    for m in visible_models(product):
        controls = model_controls(m)
        mid = m.get("id")
        items.append({
            "model_id": f"{prefix}/{mid}",
            "upstream_model": mid,
            "display_name": m.get("name") or mid,
            "region": prefix,
            "is_multimodal": controls["supports_images"],
            "context_window": controls["max_input_tokens"],
            "max_output_tokens": controls["max_output_tokens"],
            "supports_tools": controls["supports_tools"],
            "supports_images": controls["supports_images"],
            "reasoning_efforts": controls["efforts"],
        })
    return items


async def fetch_catalog(region: str, credential: dict) -> dict:
    data = await call(region, "/v3/config", credential=credential, timeout=30,
                      headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
    return data if isinstance(data, dict) else {}


async def list_models(region: str, credential: dict) -> list[dict]:
    return catalog_models(region, await fetch_catalog(region, credential))


# ------------------------------------------------------------------ 对话

def prepare_chat(chat: dict, region: str) -> dict:
    """OpenAI chat 请求 -> 上游请求体（合并指令、补默认 system、强制流式）。"""
    body = copy.deepcopy(chat or {})
    body.pop("stream", None)
    body.pop("stream_options", None)
    if "max_completion_tokens" in body and "max_tokens" not in body:
        body["max_tokens"] = body.pop("max_completion_tokens")

    system: list[str] = []
    developer: list[str] = []
    conversation: list[dict] = []
    for message in body.get("messages") or []:
        role = message.get("role")
        if role in ("system", "developer"):
            text = message.get("content", "")
            if isinstance(text, list):
                text = "\n".join(
                    p.get("text", "") for p in text
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            (system if role == "system" else developer).append(text or "")
        else:
            conversation.append(message)

    messages = conversation
    if system or developer:
        instructions = "\n".join(system)
        if developer:
            if instructions:
                instructions += "\n\nAdditional developer instructions (subject to the system instructions above):\n"
            instructions += "\n".join(developer)
        messages = [{"role": "system", "content": instructions}] + conversation
    body["messages"] = messages

    if normalize_region(region) == "intl" and (not messages or messages[0].get("role") != "system"):
        body["messages"].insert(0, {"role": "system", "content": DEFAULT_SYSTEM_PROMPT})

    fmt = body.get("response_format")
    if isinstance(fmt, dict) and fmt.get("type") in ("json_object", "json_schema"):
        text = "Return only valid JSON, without markdown fences or commentary."
        if fmt["type"] == "json_schema":
            schema = (fmt.get("json_schema") or {}).get("schema", {})
            text += " Follow this JSON schema: " + json.dumps(schema, ensure_ascii=False)
        body["messages"].insert(0, {"role": "system", "content": text})

    body["stream"] = True
    body["stream_options"] = {"include_usage": True}
    return body


def _check_chunk(chunk: dict) -> dict:
    if not isinstance(chunk, dict):
        raise WorkBuddyError(502, "Invalid stream chunk", "invalid_stream_chunk")
    if chunk.get("error") or chunk.get("code") not in (None, 0, 200, "0", "200"):
        err = chunk.get("error") if isinstance(chunk.get("error"), dict) else chunk
        message = str(err.get("message") or err.get("msg") or "Upstream stream error")
        raise WorkBuddyError(502, message[:500], "upstream_" + str(err.get("code", "error")))
    if not isinstance(chunk.get("choices"), list):
        raise WorkBuddyError(502, "Missing choices", "invalid_stream_chunk")
    return chunk


async def stream_chunks(
    region: str, credential: dict, model_id: str, chat: dict,
    conversation_id: str = "", timeout: float = 600,
):
    """调用 /v2/chat/completions，逐个 yield 上游 SSE chunk（dict）。"""
    region = normalize_region(region)
    _, bare_model = strip_model_prefix(model_id)
    body = prepare_chat(chat, region)
    body["model"] = bare_model

    request_id = "req_" + uuid.uuid4().hex
    conversation_id = conversation_id or ("conv_" + uuid.uuid4().hex)
    extra = {
        "X-Model-ID": bare_model,
        "X-Agent-Intent": "craft",
        "X-Agent-Purpose": "conversation",
        "x-codebuddy-request": "1",
        "X-Private-Data": "true",
        "X-Conversation-ID": conversation_id,
        "X-Conversation-Request-ID": request_id,
        "X-Conversation-Message-ID": request_id,
    }
    url = _config(region)["endpoint"].rstrip("/") + "/v2/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream("POST", url, headers={**_headers(region, credential), **extra}, json=body) as resp:
                if resp.status_code >= 400:
                    raw = await resp.aread()
                    status = resp.status_code if resp.status_code < 500 else 502
                    raise WorkBuddyError(status, _error_text(raw, resp.status_code), "upstream_error")
                if "text/event-stream" in (resp.headers.get("content-type") or ""):
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload:
                            continue
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except ValueError:
                            raise WorkBuddyError(502, "Malformed SSE JSON", "invalid_sse_json")
                        yield _check_chunk(chunk)
                    return
                # 非 SSE（错误或单包 JSON）
                raw = await resp.aread()
                try:
                    chunk = json.loads(raw)
                except ValueError:
                    raise WorkBuddyError(502, "Upstream returned non-JSON", "invalid_upstream")
                chunk = _check_chunk(chunk)
                for choice in chunk.get("choices", []):
                    choice["delta"] = choice.pop("message", {})
                    for index, tool in enumerate(choice["delta"].get("tool_calls") or []):
                        tool["index"] = index
                chunk["object"] = "chat.completion.chunk"
                yield chunk
    except httpx.TimeoutException:
        raise WorkBuddyError(504, "Upstream stream timeout", "stream_timeout")
    except httpx.HTTPError:
        raise WorkBuddyError(502, "Upstream connection failed", "upstream_connection_error")


class _Accumulator:
    """把上游增量 chunk 合并成一份完整 chat.completion。"""

    def __init__(self, model: str):
        self.value = {
            "id": "chatcmpl-" + uuid.uuid4().hex[:12],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
        }
        self.choices: dict[int, dict] = {}

    def add(self, chunk: dict):
        for key in ("id", "created", "model", "system_fingerprint", "service_tier", "usage"):
            if key in chunk:
                self.value[key] = chunk[key]
        for choice in chunk.get("choices") or []:
            index = choice.get("index", 0)
            target = self.choices.setdefault(index, {
                "index": index,
                "message": {"role": "assistant", "content": None},
                "finish_reason": None,
            })
            message = target["message"]
            delta = choice.get("delta") or {}
            for key in ("content", "reasoning_content", "refusal"):
                if delta.get(key) is not None:
                    message[key] = (message.get(key) or "") + delta[key]
            for tool in delta.get("tool_calls") or []:
                calls = message.setdefault("tool_calls", [])
                position = tool.get("index", 0)
                while len(calls) <= position:
                    calls.append(None)
                if calls[position] is None:
                    calls[position] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                call = calls[position]
                if tool.get("id"):
                    call["id"] = tool["id"]
                for key in ("name", "arguments"):
                    call["function"][key] += (tool.get("function") or {}).get(key, "")
            if delta.get("function_call"):
                call = message.setdefault("function_call", {"name": "", "arguments": ""})
                for key in call:
                    call[key] += delta["function_call"].get(key, "")
            if choice.get("finish_reason") is not None:
                target["finish_reason"] = choice["finish_reason"]
            if choice.get("logprobs"):
                target["logprobs"] = choice["logprobs"]

    def finish(self) -> dict:
        if not self.choices:
            raise WorkBuddyError(502, "Empty completion", "empty_completion")
        self.value["choices"] = [self.choices[i] for i in sorted(self.choices)]
        for choice in self.value["choices"]:
            choice.setdefault("finish_reason", "stop")
            for call in choice["message"].get("tool_calls") or []:
                if not call or not call.get("id") or not call["function"]["name"]:
                    raise WorkBuddyError(502, "Incomplete tool call", "invalid_tool_call")
        return self.value


async def chat_completion(
    region: str, credential: dict, model_id: str, chat: dict,
    conversation_id: str = "", timeout: float = 600,
) -> dict:
    """非流式对话：上游流式返回后本地聚合成 OpenAI chat.completion。"""
    accumulator = _Accumulator(model_id)
    async for chunk in stream_chunks(region, credential, model_id, chat, conversation_id, timeout):
        accumulator.add(chunk)
    return accumulator.finish()


# ------------------------------------------------------------------ ApiKey 辅助

def load_credential(api_key, access_token: str = "") -> dict:
    """ApiKey 行 -> 上游凭据字典。"""
    from app.utils.crypto import decrypt_value

    blob: dict = {}
    if api_key.oauth_refresh:
        try:
            parsed = json.loads(decrypt_value(api_key.oauth_refresh))
            if isinstance(parsed, dict):
                blob = parsed
        except Exception:
            blob = {}
    credential = dict(blob)
    credential["access_token"] = access_token or decrypt_value(api_key.key_value)
    return credential


def resolve_region(credential: dict, base_url: str = "") -> str:
    """凭据里的 region 优先，其次按 provider.base_url 域名推断。"""
    if credential.get("region"):
        return normalize_region(credential["region"])
    host = (urllib.parse.urlsplit(base_url or "").hostname or "").lower()
    if host.endswith("workbuddy.ai") or host.endswith("codebuddy.ai"):
        return "intl"
    return "cn"


async def refresh_key(db, api_key) -> None:
    """刷新某个 CLI 导入的 WorkBuddy 凭据（过期前 60s 才真正请求上游）。"""
    from app.utils.crypto import decrypt_value, encrypt_value

    if not api_key.oauth_refresh:
        return
    try:
        blob = json.loads(decrypt_value(api_key.oauth_refresh))
    except Exception:
        return
    if not isinstance(blob, dict) or not blob.get("refresh_token"):
        return
    if api_key.oauth_expires_at and api_key.oauth_expires_at > time.time() + 60:
        return

    region = normalize_region(blob.get("region", "cn"))
    credential = dict(blob)
    credential["access_token"] = decrypt_value(api_key.key_value)
    try:
        updated = await refresh_credential(region, credential)
    except WorkBuddyError as e:
        api_key.last_error = f"WorkBuddy refresh failed: {e.message}"[:500]
        if e.code == "login_required":
            api_key.status = "expired"
        await db.commit()
        return

    access = updated.pop("access_token", "")
    if access:
        api_key.key_value = encrypt_value(access)
    if updated.get("expires_at"):
        api_key.oauth_expires_at = int(updated["expires_at"] / 1000)
    api_key.oauth_refresh = encrypt_value(json.dumps(updated))
    api_key.status = "active"
    api_key.last_error = ""
    await db.commit()
