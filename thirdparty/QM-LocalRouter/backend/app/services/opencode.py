"""OpenCode 本地服务端客户端（移植并优化自 TiaraBasori/opencode2api 的连接方式）。

OpenCode 不是标准 OpenAI 端点，而是自带一个本地 HTTP 服务端（opencode serve）：
认证可选 HTTP Basic(opencode:password)，对话走 session / message / SSE event 协议。
本文件把 OpenAI chat/completions 请求翻译成 OpenCode 协议，并聚合为 OpenAI 格式。

=== 协议速查（实测 opencode 1.19.0）===
- GET  /global/health        -> {"healthy":true}
- GET  /config/providers     -> {"providers":[...]}        模型目录（列表结构）
- POST /session              -> {"id":"..."}               body.model = {providerID, id}
- POST /session/{id}/message -> 下发消息 body = {parts, model:{providerID,modelID}, system?}
- GET  /global/event         -> SSE 事件流（本次优化的核心）
- DELETE /session/{id}       -> 清理会话

=== SSE 事件流的三个坑（必须处理）===
1. 报文是**嵌套**的：data: {"payload":{"type":"...","properties":{...}}}。
   opencode2api 能直接写 event.type 是因为官方 SDK 解了包，裸 HTTP 必须手动取 payload。
2. **每个事件会被推送两次**：一次本体，一次包在 payload.type=="sync" 的壳里。
   实测 143 条原始报文只有 46 条有效，不去重等于白做 2/3 的解析。
3. `message.part.delta` **不带 type**，只有 partID；type 由前一条 message.part.updated
   宣布。必须维护 partID->type 映射，否则 reasoning 与正文无法区分，正文会被错误
   路由甚至整体丢弃。

=== 工具执行与超时（防响应截断）===
OpenCode 执行内置工具期间不会吐任何文本增量，且会发出**中间态 finish:"stop"**。
若此刻就收流，最终答案会被丢弃。必须用 activeToolCallIds 跟踪工具的 pending/running，
工具活动期间即使空闲也不断流，且忽略工具在飞时的中间 stop。

=== 上游失败时的重试事件（否则错误被吞成空回复）===
上游报错（如 "Upstream request failed: Model is unavailable."）时，opencode 并**不立刻**
发 message.updated.error，而是先发 `session.status{type:"retry", attempt, message}` 并自行
重试（默认 4 次，退避 5s/10s/20s/40s）。整个重试期间没有任何 delta，也没有 error 事件：
只按 message.updated.error 判定的话，会被 45s 空闲超时切断并返回 200 + content=null，
真实错误彻底丢失。处理办法：① 记录 retry 的 message 并 touch()（重试期间算活动，不按空闲断流）；
② 因超时收流时把记录的 message 作为 error 返回，由上层转成 502。
"""
import asyncio
import base64
import json
import re
import time
import uuid

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:4096"   # opencode serve 固定端口（10001 常被其他软件占用）
DEFAULT_MODEL = "opencode/ling-3.1-flash-free"

# 与 opencode2api 对齐：reasoning_effort 取值映射
_EFFORT_MAP = {
    "none": "none", "minimal": "none", "low": "low",
    "medium": "medium", "high": "high", "xhigh": "high",
}

# SSE 收集的三段超时（秒）；单次请求总超时仍由 self.timeout 兜住
_FIRST_DELTA_TIMEOUT = 120.0    # 首个增量到达前的等待上限
_IDLE_TIMEOUT = 45.0            # 无增量且无工具活动时的空闲上限

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def _error_message(err) -> str:
    """从 assistant error 结构里提取可读信息（兼容 {name,data:{message}} 嵌套）。"""
    if isinstance(err, str):
        return err
    if not isinstance(err, dict):
        return str(err)
    data = err.get("data") or {}
    return str(data.get("message") or err.get("message") or err)


class OpenCodeError(Exception):
    def __init__(self, status: int, message: str, code: str = "upstream_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def _auth_header(password: str) -> dict:
    if not password:
        return {}
    token = base64.b64encode(f"opencode:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _normalize_effort(value) -> str | None:
    if not value or not isinstance(value, str):
        return None
    return _EFFORT_MAP.get(value.lower())


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize_text(content):
    """OpenAI content -> 纯文本（数组 content 拼为文本）。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if p.get("type") in ("text", "input_text"):
                    parts.append(p.get("text", ""))
        return "\n".join(x for x in parts if x)
    return str(content)


def _tool_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:16]


# --------------------------------------------------------------------- 工具桥接
def _tool_registry(tools: list) -> list[dict]:
    """客户端传入的 OpenAI tools -> 内部注册表（含命名空间，避免与内置工具冲突）。"""
    registry: list[dict] = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else {}
        name = fn.get("name") or t.get("name")
        if not name:
            continue
        registry.append({
            "name": name,
            "namespaced_name": f"ext_{name}",
            "description": fn.get("description") or "",
            "parameters": fn.get("parameters") or {},
        })
    return registry


def _tool_system_section(registry: list[dict], forced: str | None = None) -> str:
    """把外部工具说明注入 system：要求模型用 <tool_call> 块输出调用意图。"""
    if not registry:
        return ""
    lines = ["你可以使用以下工具。需要调用工具时，必须输出如下格式的块（可多个，块外不要写其它内容）：",
             "",
             '<tool_call>',
             '{"name": "<工具名>", "arguments": {<参数 JSON 对象>}}',
             '</tool_call>',
             "",
             "可用工具："]
    for item in registry:
        schema = json.dumps(item["parameters"], ensure_ascii=False) if item["parameters"] else "{}"
        lines.append(f"- {item['name']}：{item['description'] or '（无描述）'}")
        lines.append(f"  参数 schema：{schema}")
    if forced:
        lines.append("")
        lines.append(f"本次必须调用工具 `{forced}`，直接输出对应的 <tool_call> 块，不要回答其它内容。")
    return "\n".join(lines)


def _parse_tool_calls(text: str, registry: list[dict]) -> tuple[str, list[dict]]:
    """从模型输出里抽出 <tool_call> 块，转成 OpenAI tool_calls；返回（剩余正文, tool_calls）。"""
    if not text or not registry:
        return text, []
    valid = {item["name"]: item for item in registry}
    calls: list[dict] = []
    clean = text
    for match in _TOOL_CALL_RE.finditer(text):
        raw = match.group(1).strip()
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, list):
            objs = obj
        elif isinstance(obj, dict):
            objs = [obj]
        else:
            continue
        for one in objs:
            if not isinstance(one, dict):
                continue
            name = one.get("name")
            if name not in valid:
                continue
            args = one.get("arguments") or {}
            calls.append({
                "index": len(calls),
                "id": _tool_call_id(),
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)
                             if not isinstance(args, str) else args},
            })
    if calls:
        clean = _TOOL_CALL_RE.sub("", clean).strip()
    return clean, calls


class _ToolCallStreamFilter:
    """流式场景：跨增量识别完整的 <tool_call> 块。

    块未闭合前扣住文本（避免把半个块当正文吐出去），闭合后转成 tool_call 增量。
    """

    OPEN = "<tool_call>"

    def __init__(self, registry: list[dict]):
        self.registry = registry
        self.buf = ""
        self.emitted = 0

    def push(self, delta: str) -> tuple[str, list[dict]]:
        if not self.registry:
            return delta, []
        self.buf += delta
        safe = self.buf
        # 保留尾部可能未闭合的开头，避免吐出半个块
        open_at = safe.rfind(self.OPEN)
        if open_at != -1 and "</tool_call>" not in safe[open_at:]:
            flush, keep = safe[:open_at], safe[open_at:]
        else:
            flush, keep = safe, ""
        clean, calls = _parse_tool_calls(flush, self.registry)
        self.buf = keep
        if calls:
            clean = clean.lstrip()
        return clean, calls

    def flush(self) -> tuple[str, list[dict]]:
        if not self.registry:
            return "", []
        clean, calls = _parse_tool_calls(self.buf, self.registry)
        self.buf = ""
        return clean, calls


class OpenCodeClient:
    def __init__(self, base_url: str, password: str = "", timeout: float = 600,
                 bridge_tools: bool = False):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.password = password or ""
        self.timeout = timeout
        # 外部工具桥接开关，默认关闭。原因见 _bridge_enabled 注释。
        self.bridge_tools = bridge_tools

    def _bridge_enabled(self, registry: list, tool_choice) -> bool:
        """是否启用外部工具桥接（把客户端 tools 翻译成 <tool_call> 文本协议）。

        默认关闭是有实测依据的，不是保守：
        - 不禁用内置工具时，模型自带 bash / google_search / websearch 等真实工具，
          会直接无视 system prompt 里注入的外挂工具。
        - 试图用 tools:{name:false} 禁用内置工具则会撞上免费层风控：
          * 名字写错/不存在 -> 大量 session.error，请求挂死；
          * 全部禁用成功 -> 上游 403 "OpenCode's free tier can only be used from
            within OpenCode"（零工具 = 非官方客户端特征）。
        结论：本免费层上可靠的函数调用不可得。保留实现供可按上述限制自行部署的场景
        （自建 Claude API key 等付费模型、或愿意接受尽力而为结果）显式开启。
        """
        return bool(self.bridge_tools and registry and tool_choice != "none")

    # ----------------------------------------------------------------- 请求
    async def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = self.base_url + path
        headers = {"Content-Type": "application/json", **_auth_header(self.password)}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                resp = await client.request(method, url, json=body, headers=headers)
        except httpx.TimeoutException:
            raise OpenCodeError(504, "OpenCode 服务端超时", "timeout")
        except httpx.HTTPError as e:
            raise OpenCodeError(502, f"无法连接 OpenCode 服务端: {e}", "connection_error")

        if resp.status_code == 401:
            raise OpenCodeError(401, "OpenCode 服务端密码错误或未授权", "unauthorized")
        if resp.status_code >= 400:
            text = resp.text[:300] or f"HTTP {resp.status_code}"
            raise OpenCodeError(resp.status_code, f"OpenCode 服务端错误: {text}", "upstream_error")
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            raise OpenCodeError(502, "OpenCode 返回非 JSON", "invalid_upstream")

    # ----------------------------------------------------------------- 健康检查
    async def health(self) -> bool:
        data = await self._request("GET", "/global/health")
        return bool(data.get("healthy"))

    # ----------------------------------------------------------------- 模型目录
    async def list_models(self) -> list[dict]:
        data = await self._request("GET", "/config/providers")
        providers = data.get("providers") or []
        if isinstance(providers, dict):
            providers = [{"id": pid, **info} for pid, info in providers.items()]
        models: list[dict] = []
        for p in providers:
            pid = p.get("id") or p.get("name")
            pmodels = p.get("models") or {}
            if isinstance(pmodels, dict):
                for mid, mdata in pmodels.items():
                    if not isinstance(mdata, dict):
                        mdata = {}
                    name = mdata.get("name") or mdata.get("label") or mid
                    release = mdata.get("release_date")
                    try:
                        created = int(time.mktime(time.strptime(release, "%Y-%m-%d"))) if release else 1704067200
                    except (ValueError, TypeError):
                        try:
                            created = int(time.mktime(time.strptime(release, "%Y-%m")))
                        except (ValueError, TypeError):
                            created = 1704067200
                    models.append({
                        "id": f"{pid}/{mid}",
                        "name": name,
                        "owned_by": pid,
                        "object": "model",
                        "created": created,
                    })
        return models

    # ----------------------------------------------------------------- 会话
    async def _create_session(self, model: dict, title: str | None = None) -> str:
        body: dict = {"model": {"providerID": model["providerID"], "id": model["modelID"]}}
        if title:
            body["title"] = title
        data = await self._request("POST", "/session", body)
        sid = data.get("id")
        if not sid:
            raise OpenCodeError(502, "OpenCode 未能创建会话", "no_session")
        return sid

    async def _prompt(self, session_id: str, model: dict, system: str | None, parts: list) -> None:
        body: dict = {"parts": parts, "model": model}
        if system:
            body["system"] = system
        await self._request("POST", f"/session/{session_id}/message", body)

    async def _delete_session(self, session_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                await client.request("DELETE", f"{self.base_url}/session/{session_id}",
                                    headers=_auth_header(self.password))
        except Exception:
            pass

    @staticmethod
    def _resolve_model(model_id: str) -> dict:
        if not model_id or "/" not in model_id:
            return {"providerID": "opencode", "modelID": model_id or DEFAULT_MODEL.split("/")[-1]}
        provider_id, mid = model_id.split("/", 1)
        return {"providerID": provider_id, "modelID": mid}

    def _build_parts(self, messages: list) -> tuple[str | None, list]:
        """OpenAI messages -> OpenCode prompt parts。

        整段对话压成一条 prompt 的 parts（角色前缀区分），system 单独抽取。
        tool 结果不再丢弃：转成 TOOL_RESULT 文本，让多轮工具循环能续得上。
        """
        system_chunks: list[str] = []
        parts: list[dict] = []
        for m in messages or []:
            role = (m.get("role") or "user").lower()
            content = m.get("content")
            if role == "system":
                text = _normalize_text(content)
                if text:
                    system_chunks.append(text)
                continue
            if role == "tool":
                # 客户端回传的工具结果：作为上下文文本续进 prompt
                name = m.get("name") or (m.get("tool_call_id") or "tool")
                text = _normalize_text(content)
                if text:
                    parts.append({"type": "text", "text": f"TOOL_RESULT[{name}]: {text}"})
                continue
            text = _normalize_text(content)
            if not text:
                continue
            parts.append({"type": "text", "text": f"{role.upper()}: {text}"})
        return ("\n\n".join(system_chunks) if system_chunks else None), parts

    # ----------------------------------------------------------------- SSE
    async def _subscribe(self, ready: asyncio.Event):
        """产出解包后的 SSE 事件 {type, properties}（自动跳过 sync 重复包）。

        作为 async generator 使用；ready 在建立连接并收到首个事件后被置位，
        确保 caller 在订阅存活后才下发 prompt，避免丢失早期事件。
        """
        url = self.base_url + "/global/event"
        headers = {**_auth_header(self.password), "Accept": "text/event-stream"}
        seen_ready = False
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10), trust_env=False) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        env = json.loads(payload)
                    except ValueError:
                        continue
                    if not isinstance(env, dict):
                        continue
                    # 真实结构为 {payload:{type,properties}}，SDK 会解包，这里手动取
                    ev = env.get("payload") if isinstance(env.get("payload"), dict) else env
                    etype = ev.get("type")
                    if not etype or etype == "sync":
                        # "sync" 是同一事件的重复推送（实测约占 2/3），直接丢弃
                        if not seen_ready:
                            seen_ready = True
                            ready.set()
                        continue
                    if not seen_ready:
                        seen_ready = True
                        ready.set()
                    yield {"type": etype, "properties": ev.get("properties") or {}}

    async def _collect(self, session_id: str, on_delta=None, timeout: float | None = None,
                       on_ready=None):
        """订阅 SSE 并收集一条 assistant 回复的全文。

        对应 opencode2api 的 collectFromEvents，含三段超时与工具感知续流：
        - 全局超时 / 首字超时 / 空闲超时（空闲以**最后一次活动**为基准，持续输出不会误断）
        - partID->type 映射，区分 reasoning 与正文
        - 跟踪工具的 pending/running：工具执行期间不切断流
        - 忽略工具在飞时发出的中间态 finish:"stop"，避免丢最终答案

        on_ready 在 SSE 订阅确认存活后被调用（用于下发 prompt），保证不漏早期事件。
        """
        timeout = timeout or self.timeout
        content, reasoning = "", ""
        active_tools: set[str] = set()
        part_types: dict[str, str] = {}
        # 用可变容器承载标量状态，避免 nonlocal 的闭包陷阱
        state = {"got_delta": False, "last": time.monotonic(),
                 "retry_error": None, "retry_attempts": 0}

        def touch():
            """标记一次“有进展”，用于空闲计时重置。"""
            state["last"] = time.monotonic()

        def result_with_error(flag: str):
            """因超时收流时，若期间上游在重试报错，把真实错误带出去，别静默返回空内容。"""
            out = {"content": content, "reasoning": reasoning, flag: True}
            if state["retry_error"]:
                out["error"] = {"name": "UpstreamRetryExhausted",
                                "data": {"message": state["retry_error"]}}
            return out

        ready = asyncio.Event()

        def track_tool(part):
            if not isinstance(part, dict) or part.get("type") != "tool":
                return
            status = (part.get("state") or {}).get("status")
            pid_ = part.get("id")
            if not pid_:
                return
            if status in ("pending", "running"):
                active_tools.add(pid_)
            elif status in ("completed", "error"):
                active_tools.discard(pid_)
            touch()  # 工具的任何状态变化都算活动

        def apply_delta(part_type: str, delta: str):
            nonlocal content, reasoning
            if not isinstance(delta, str) or not delta:
                return
            touch()
            state["got_delta"] = True
            if part_type == "reasoning":
                reasoning += delta
                if on_delta:
                    on_delta(delta, True)
            else:
                content += delta
                if on_delta:
                    on_delta(delta, False)

        async def consume():
            async for ev in self._subscribe(ready):
                etype, props = ev["type"], ev["properties"]
                if props.get("sessionID") != session_id:
                    continue
                if etype == "session.status":
                    # 上游失败时 opencode 自己会重试（默认 4 次），期间既无 delta 也无
                    # message.updated.error，只发 status.type=="retry"。必须：
                    # ① 记下报错，供超时收流时透出真实原因；
                    # ② 视作活动，否则会被空闲超时误判为「模型没输出」而返回空内容。
                    status = props.get("status") or {}
                    if isinstance(status, dict) and status.get("type") == "retry":
                        state["retry_error"] = status.get("message") or state["retry_error"]
                        try:
                            state["retry_attempts"] = max(state["retry_attempts"],
                                                          int(status.get("attempt") or 0))
                        except (TypeError, ValueError):
                            pass
                        touch()
                    continue
                if etype == "message.part.updated":
                    part = props.get("part") or {}
                    if isinstance(part, dict) and part.get("id") and isinstance(part.get("type"), str):
                        part_types[part["id"]] = part["type"]
                    track_tool(part)
                    # 旧版服务端把 delta 直接挂在 updated 上
                    delta = props.get("delta")
                    if isinstance(delta, str) and part.get("type") in ("text", "reasoning"):
                        apply_delta(part["type"], delta)
                    continue
                if etype == "message.part.delta":
                    if props.get("field") != "text":
                        continue
                    delta = props.get("delta")
                    if not isinstance(delta, str):
                        continue
                    # delta 不带 type，必须靠 partID 回查前一条 updated 宣布的类型
                    part_type = part_types.get(props.get("partID"))
                    if part_type in ("text", "reasoning"):
                        apply_delta(part_type, delta)
                    continue
                if etype == "message.updated":
                    info = props.get("info") or {}
                    if info.get("error"):
                        return {"content": content, "reasoning": reasoning, "error": info["error"]}
                    # 用完整快照对账工具状态（只收到 updated 而没收 part 事件时兜底）
                    for part in (info.get("parts") or []):
                        if isinstance(part, dict):
                            if part.get("id") and isinstance(part.get("type"), str):
                                part_types[part["id"]] = part["type"]
                            track_tool(part)
                    finish = info.get("finish")
                    if finish == "tool":
                        continue  # 助手回合在等工具结果，继续收集
                    if finish == "stop":
                        # 工具仍在飞时，这可能是中间态快照，忽略以免丢最终答案
                        if active_tools:
                            continue
                        return {"content": content, "reasoning": reasoning}
                    continue
            return {"content": content, "reasoning": reasoning}

        # 必须先让订阅跑起来再等 ready，否则就绪事件永远不会产生（死锁）
        touch()
        task = asyncio.create_task(consume())
        try:
            await asyncio.wait_for(ready.wait(), timeout=10)
        except asyncio.TimeoutError:
            task.cancel()
            raise OpenCodeError(502, "OpenCode 事件流订阅失败", "sse_error")

        if on_ready:
            await on_ready()   # 订阅已存活，此时下发 prompt 不会漏事件

        start = time.monotonic()
        while True:
            if task.done():
                return task.result()
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                task.cancel()
                raise OpenCodeError(504, "OpenCode 响应超时", "timeout")
            if not state["got_delta"] and elapsed >= min(_FIRST_DELTA_TIMEOUT, timeout):
                task.cancel()
                return result_with_error("no_data")
            idle_for = time.monotonic() - state["last"]
            if idle_for >= min(_IDLE_TIMEOUT, timeout):
                # 工具还在执行就继续等，否则会截断依赖工具执行的回答
                if active_tools:
                    await asyncio.sleep(0.5)
                    continue
                task.cancel()
                return result_with_error("idle_timeout")
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------- 轮询降级
    async def _wait_for_completion(self, session_id: str, interval: float = 0.4) -> dict:
        """SSE 不可用时的降级路径：轮询消息快照。"""
        deadline = time.time() + self.timeout
        last: dict = {"content": "", "reasoning": "", "error": None, "done": False}
        while time.time() < deadline:
            data = await self._request("GET", f"/session/{session_id}/message")
            snap = self._poll_snapshot(data)
            if snap["content"] or snap["reasoning"] or snap["error"]:
                last = snap
            if snap["done"]:
                return snap
            await asyncio.sleep(interval)
        if last.get("done"):
            return last
        raise OpenCodeError(504, "OpenCode 响应超时", "timeout")

    @staticmethod
    def _poll_snapshot(data) -> dict:
        messages = data if isinstance(data, list) else (data.get("messages") or [])
        content, reasoning, error, finish, completed = "", "", None, None, False
        for entry in reversed(messages):
            info = entry.get("info") or {}
            if info.get("role") != "assistant":
                continue
            parts = entry.get("parts") or []
            content = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
            reasoning = "".join(p.get("text", "") for p in parts if p.get("type") == "reasoning")
            error = info.get("error")
            finish = info.get("finish")
            completed = bool(info.get("time", {}).get("completed")) if isinstance(info.get("time"), dict) else False
            break
        done = bool(finish and finish != "tool") or completed or bool(error)
        return {"content": content, "reasoning": reasoning, "error": error, "done": done}

    # ------------------------------------------------------------- 非流式
    async def chat_completion(
        self, messages: list, model_id: str, reasoning_effort: str | None = None,
        temperature: float = 0.7, max_tokens: int | None = None,
        tools: list | None = None, tool_choice=None,
    ) -> dict:
        model = self._resolve_model(model_id)
        system, parts = self._build_parts(messages)
        registry = _tool_registry(tools)

        forced: str | None = None
        if isinstance(tool_choice, dict):
            forced = (tool_choice.get("function") or {}).get("name")
        elif isinstance(tool_choice, str) and tool_choice not in ("auto", "none", ""):
            forced = tool_choice
        inject = self._bridge_enabled(registry, tool_choice)
        if inject:
            section = _tool_system_section(registry, forced)
            system = f"{system}\n\n{section}" if system else section

        prompted = {"done": False}

        async def _send(prompt_parts=None):
            if prompted["done"]:
                return
            await self._prompt(session_id, model, system, prompt_parts or parts)
            prompted["done"] = True

        session_id = await self._create_session(model)
        try:
            try:
                # on_ready 保证「订阅存活后才发 prompt」，避免漏掉紧随其后的事件
                result = await self._collect(session_id, on_ready=lambda: _send())
            except OpenCodeError:
                await _send()  # SSE 不可用 -> 降级轮询
                result = await self._wait_for_completion(session_id)
            if result.get("error"):
                raise OpenCodeError(502, _error_message(result["error"]), "assistant_error")

            finish_reason = "stop"
            content = result.get("content") or ""
            reasoning = result.get("reasoning") or ""
            tool_calls: list[dict] = []
            if inject:
                content, tool_calls = _parse_tool_calls(content, registry)
                if tool_calls:
                    finish_reason = "tool_calls"
                elif forced:
                    # 要求必须调用工具却没产出 -> 强提示追问一次
                    retry_parts = parts + [{"type": "text",
                                            "text": f"请仅输出调用 `{forced}` 的 <tool_call> 块，不要输出其它内容。"}]
                    try:
                        result = await self._collect(
                            session_id, on_ready=lambda: self._prompt(session_id, model, system, retry_parts))
                    except OpenCodeError:
                        await self._prompt(session_id, model, system, retry_parts)
                        result = await self._wait_for_completion(session_id)
                    content = result.get("content") or content
                    reasoning = result.get("reasoning") or reasoning
                    content, tool_calls = _parse_tool_calls(content, registry)
                    if tool_calls:
                        finish_reason = "tool_calls"
        finally:
            await self._delete_session(session_id)

        if not content and reasoning:
            # 免费通道偶发整条只有 reasoning，回退给正文保证客户端可见
            content, reasoning = reasoning, ""

        message: dict = {"role": "assistant", "content": content or None}
        if reasoning:
            message["reasoning_content"] = reasoning
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "id": "chatcmpl-" + _short_id(),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_id,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # --------------------------------------------------------------- 流式
    async def stream_chunks(
        self, messages: list, model_id: str, reasoning_effort: str | None = None,
        temperature: float = 0.7, max_tokens: int | None = None,
        tools: list | None = None, tool_choice=None,
    ):
        model = self._resolve_model(model_id)
        system, parts = self._build_parts(messages)
        registry = _tool_registry(tools)

        forced: str | None = None
        if isinstance(tool_choice, dict):
            forced = (tool_choice.get("function") or {}).get("name")
        elif isinstance(tool_choice, str) and tool_choice not in ("auto", "none", ""):
            forced = tool_choice
        inject = self._bridge_enabled(registry, tool_choice)
        if inject:
            section = _tool_system_section(registry, forced)
            system = f"{system}\n\n{section}" if system else section

        completion_id = "chatcmpl-" + _short_id()
        tc_filter = _ToolCallStreamFilter(registry) if inject else None
        queue: asyncio.Queue = asyncio.Queue()
        finish = {"reason": "stop"}

        def now_chunk(delta: dict):
            return {"id": completion_id, "object": "chat.completion.chunk",
                    "created": int(time.time()), "model": model_id,
                    "choices": [{"index": 0, "delta": delta}]}

        def emit_tool_call(call: dict):
            finish["reason"] = "tool_calls"
            queue.put_nowait(now_chunk({"tool_calls": [{
                "index": call["index"], "id": call["id"], "type": "function",
                "function": {"name": call["function"]["name"], "arguments": call["function"]["arguments"]},
            }]}))

        def on_delta(text, is_reasoning):
            if is_reasoning:
                queue.put_nowait(now_chunk({"reasoning_content": text}))
                return
            if tc_filter:
                clean, calls = tc_filter.push(text)
                if clean:
                    queue.put_nowait(now_chunk({"content": clean}))
                for call in calls:
                    emit_tool_call(call)
            else:
                queue.put_nowait(now_chunk({"content": text}))

        prompted = {"done": False}

        async def _send():
            if prompted["done"]:
                return
            await self._prompt(session_id, model, system, parts)
            prompted["done"] = True

        session_id = await self._create_session(model)
        task = asyncio.create_task(self._collect(session_id, on_delta=on_delta, on_ready=_send))
        try:
            # 实时下发：收集器把增量塞进队列，这里边到边转给客户端，不等全部完成
            while True:
                if task.done() and queue.empty():
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.3)
                except asyncio.TimeoutError:
                    continue
            while not queue.empty():
                yield queue.get_nowait()

            sse_failed = None
            try:
                result = await task
            except OpenCodeError as e:
                sse_failed = e
                result = None

            if sse_failed is not None and not prompted["done"]:
                # SSE 订阅失败（prompt 还没发出）-> 降级轮询后整段补发
                await _send()
                snap = await self._wait_for_completion(session_id)
                text = snap.get("content") or ""
                if text:
                    clean, calls = tc_filter.push(text) if tc_filter else (text, [])
                    if clean:
                        yield now_chunk({"content": clean})
                    for call in calls:
                        emit_tool_call(call)
                if tc_filter:
                    clean, calls = tc_filter.flush()
                    if clean:
                        yield now_chunk({"content": clean})
                    for call in calls:
                        emit_tool_call(call)
                if snap.get("error"):
                    raise OpenCodeError(502, _error_message(snap["error"]), "assistant_error")
            elif sse_failed is not None:
                raise sse_failed
            else:
                if tc_filter:
                    clean, calls = tc_filter.flush()
                    if clean:
                        yield now_chunk({"content": clean})
                    for call in calls:
                        emit_tool_call(call)
                if isinstance(result, dict) and result.get("error"):
                    raise OpenCodeError(502, _error_message(result["error"]), "assistant_error")
        finally:
            task.cancel()
            await self._delete_session(session_id)

        yield {"id": completion_id, "object": "chat.completion.chunk",
               "created": int(time.time()), "model": model_id,
               "choices": [{"index": 0, "delta": {}, "finish_reason": finish["reason"]}],
               "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
