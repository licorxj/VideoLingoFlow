"""In-process LLM router: reads QM-LocalRouter SQLite DB directly,
selects strategy/rule/provider/key, makes upstream HTTP requests,
and logs to request_logs — all without the localhost HTTP gateway.

Thread-safe singleton. Uses sync sqlite3 (open/close per operation)
and sync httpx.Client with connection pooling.
"""
import json
import os
import random
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ROUTER_DATA_DIR = _PROJECT_ROOT / "thirdparty" / "QM-LocalRouter" / "backend" / "data"
_DB_PATH = _ROUTER_DATA_DIR / "app.db"
_KEY_FILE = _ROUTER_DATA_DIR / ".encryption_key"

# ---------------------------------------------------------------------------
# Cache TTL (seconds): how long resolved strategy/provider/model stay fresh
# ---------------------------------------------------------------------------
_CACHE_TTL = 60

# ---------------------------------------------------------------------------
# Fernet key (loaded once at import)
# ---------------------------------------------------------------------------
_fernet = None

# api_keys 是否已迁移 status_until/fail_count 新列（None=未知，首次查询后确定）
_has_extended_key_columns: bool | None = None

def _load_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    try:
        from cryptography.fernet import Fernet
        if _KEY_FILE.exists():
            _fernet = Fernet(_KEY_FILE.read_bytes().strip())
        else:
            _fernet = None
    except Exception:
        _fernet = None
    return _fernet


def _decrypt(ciphertext: str) -> str:
    f = _load_fernet()
    if f is None:
        return ciphertext  # fallback: assume plaintext
    return f.decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# DB helpers (sync sqlite3, open/close per call for concurrency safety)
# ---------------------------------------------------------------------------
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # enable WAL for concurrent read/write
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ---------------------------------------------------------------------------
# Strategy / Rule / Provider / Model / Key data structures
# ---------------------------------------------------------------------------
class _ResolvedRoute:
    """Result of strategy resolution: the upstream endpoint + credentials."""
    __slots__ = (
        "strategy_id", "strategy_name", "timeout", "retry_count",
        "rule_id", "provider_id", "provider_name", "provider_protocol",
        "provider_base_url", "model_id", "model_model_id", "model_display_name",
        "api_key_id", "api_key_decrypted",
    )

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k))


# ---------------------------------------------------------------------------
# Balancer logic (ported from QM-LocalRouter/services/balancer.py)
# ---------------------------------------------------------------------------
def _select_rule(rules: list[dict], lb_strategy: str,
                 rr_index: dict, strategy_id: int,
                 exclude_rule_ids: set | None = None) -> dict | None:
    if not rules:
        return None
    if exclude_rule_ids:
        remaining = [r for r in rules if r["id"] not in exclude_rule_ids]
        if remaining:
            rules = remaining

    if lb_strategy == "round_robin":
        idx = rr_index.get(strategy_id, 0) % len(rules)
        rr_index[strategy_id] = idx + 1
        return rules[idx]
    elif lb_strategy == "weighted":
        total = sum(r.get("weight", 1) for r in rules)
        if total == 0:
            return rules[0]
        pick = random.uniform(0, total)
        cur = 0
        for r in rules:
            cur += r.get("weight", 1)
            if pick <= cur:
                return r
        return rules[-1]
    elif lb_strategy == "random":
        return random.choice(rules)
    else:  # failover / priority / default
        return rules[0]


# ---------------------------------------------------------------------------
# API Key 健康判定（与 thirdparty/QM-LocalRouter/backend/app/utils/key_health.py 保持一致）
#   原则：连不通(DNS/拒连/TLS/超时)、限流(429)、上游 5xx 一律不弃用 key；
#         只有上游明确答复 401/403 且连续达阈值，才置 inactive。
# ---------------------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


#: 连续多少次 401/403 才弃用 key（1 = 旧行为，立即弃用）
AUTH_CONFIRM_THRESHOLD = _env_int("QM_KEY_AUTH_CONFIRM_THRESHOLD", 2)
#: 429 冷却秒数，到期自动恢复 active；0 = 不冷却
RATE_LIMIT_COOLDOWN = _env_int("QM_KEY_RATE_LIMIT_COOLDOWN", 60)

_USABLE_STATUS = ("active", "untested")
_TRANSPORT_EXC_NAMES = {
    "TransportError", "TimeoutException", "ConnectError", "ConnectTimeout",
    "ReadTimeout", "WriteTimeout", "PoolTimeout", "ReadError", "WriteError",
    "CloseError", "ProxyError", "UnsupportedProtocol", "LocalProtocolError",
    "RemoteProtocolError", "NetworkError", "SSLError", "SSLCertVerificationError",
    "OSError", "TimeoutError", "ConnectionError",
}


def _classify_status(status_code: int | None) -> str:
    if status_code is None:
        return "unknown"
    code = int(status_code)
    if 200 <= code < 300:
        return "ok"
    if code in (401, 403):
        return "auth"
    if code == 429:
        return "rate_limit"
    if code in (408, 425, 409, 500, 502, 503, 504, 529):
        return "upstream"
    if code in (400, 404, 405, 422):
        # 模型/路径/参数不对，与 key 是否有效无关
        return "config"
    return "client_error"


def _classify_exception(exc: BaseException) -> str:
    names = {c.__name__ for c in type(exc).__mro__}
    if "HTTPStatusError" in names:
        resp = getattr(exc, "response", None)
        return _classify_status(getattr(resp, "status_code", None))
    if names & _TRANSPORT_EXC_NAMES:
        return "unreachable"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "unreachable"
    return "unknown"


def _next_key_state(status: str | None, fail_count: int, kind: str,
                    now: float | None = None) -> tuple[str | None, int, int]:
    """算出新的 (status, fail_count, status_until)；status=None 表示保持不变。"""
    ts = int(now or time.time())
    fails = int(fail_count or 0)
    if kind == "ok":
        return "active", 0, 0
    if kind == "auth":
        fails += 1
        if fails >= max(1, AUTH_CONFIRM_THRESHOLD):
            return "inactive", fails, 0
        return None, fails, 0
    if kind == "rate_limit":
        if RATE_LIMIT_COOLDOWN > 0:
            return "rate_limited", fails, ts + RATE_LIMIT_COOLDOWN
        return None, fails, 0
    # unreachable / upstream / config / client_error：只记 last_error，不改状态
    return None, fails, 0


def _key_usable(key: dict, now: float | None = None) -> bool:
    status = (key.get("status") or "active").lower()
    if status in _USABLE_STATUS:
        return True
    if status == "rate_limited":
        return int(key.get("status_until") or 0) <= (now or time.time())
    return False


# ---------------------------------------------------------------------------
# DirectRouter singleton
# ---------------------------------------------------------------------------
class DirectRouterError(RuntimeError):
    """Raised by DirectRouter for routing/configuration failures
    (strategy not found, no active rules, provider inactive, etc.).

    Caught by llm_client._direct_chat and mapped to LLMRequestError(CONFIG).
    """
    pass


class DirectRouter:
    """In-process router that resolves strategies from the QM-LocalRouter DB
    and forwards requests directly to upstream APIs."""

    _instance: Optional["DirectRouter"] = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # Strategy cache: {name: {"data": dict, "expires": float}}
        self._strategy_cache: dict[str, dict] = {}
        self._cache_lock = threading.Lock()
        # Round-robin index
        self._rr_index: dict[int, int] = {}
        # httpx.Client pool keyed by (base_url, timeout)
        self._http_clients: dict[tuple, httpx.Client] = {}
        self._http_lock = threading.Lock()
        _load_fernet()

    # ------------------------------------------------------------------
    # Strategy resolution (with cache)
    # ------------------------------------------------------------------
    def _load_strategy(self, name: str) -> dict | None:
        """Load strategy + rules from DB (cached with TTL)."""
        now = time.time()
        with self._cache_lock:
            cached = self._strategy_cache.get(name)
            if cached and cached["expires"] > now:
                return cached["data"]

        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, name, lb_strategy, key_strategy, is_active, "
                "timeout, retry_count FROM strategies WHERE name=? AND is_active=1",
                (name,),
            )
            row = c.fetchone()
            if not row:
                return None
            strat = _row_to_dict(row)

            c.execute(
                "SELECT sr.id, sr.provider_id, sr.model_id, sr.priority, "
                "sr.weight, sr.is_active "
                "FROM strategy_rules sr WHERE sr.strategy_id=? AND sr.is_active=1 "
                "ORDER BY sr.priority, sr.id",
                (strat["id"],),
            )
            strat["rules"] = [_row_to_dict(r) for r in c.fetchall()]
        finally:
            conn.close()

        with self._cache_lock:
            self._strategy_cache[name] = {"data": strat, "expires": now + _CACHE_TTL}
        return strat

    def _load_provider(self, provider_id: int) -> dict | None:
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, name, protocol, base_url, is_active "
                "FROM providers WHERE id=? AND is_active=1",
                (provider_id,),
            )
            row = c.fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    def _load_model(self, model_db_id: int) -> dict | None:
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, provider_id, model_id, display_name, is_active "
                "FROM models WHERE id=? AND is_active=1",
                (model_db_id,),
            )
            row = c.fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    def _load_keys(self, provider_id: int) -> list[dict]:
        """Load **all** keys of a provider (any status).

        不再只取 active/untested：限流(429)冷却到期自动复活，inactive 作为
        最后兜底，避免「状态标记一旦写坏整个 provider 再也选不出 key」。
        新列 status_until/fail_count 可能尚未迁移，缺失时自动降级。
        """
        global _has_extended_key_columns
        cols_ext = "id, provider_id, key_value, status, weight, status_until, fail_count"
        cols_min = "id, provider_id, key_value, status, weight"
        conn = _get_conn()
        try:
            c = conn.cursor()
            if _has_extended_key_columns is False:
                c.execute(f"SELECT {cols_min} FROM api_keys WHERE provider_id=? ORDER BY id",
                          (provider_id,))
                return [self._normalize_key(r) for r in c.fetchall()]
            try:
                c.execute(f"SELECT {cols_ext} FROM api_keys WHERE provider_id=? ORDER BY id",
                          (provider_id,))
                _has_extended_key_columns = True
            except sqlite3.OperationalError:
                _has_extended_key_columns = False
                c.execute(f"SELECT {cols_min} FROM api_keys WHERE provider_id=? ORDER BY id",
                          (provider_id,))
            return [self._normalize_key(r) for r in c.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def _normalize_key(row: sqlite3.Row) -> dict:
        d = _row_to_dict(row)
        d.setdefault("status_until", 0)
        d.setdefault("fail_count", 0)
        return d

    def _update_key_state(self, key_id: int, kind: str, message: str = ""):
        """Persist key status per failure kind（连不通只记last_error，不弃用）。"""
        conn = _get_conn()
        try:
            c = conn.cursor()
            cur_status, fail_count, status_until = "active", 0, 0
            if _has_extended_key_columns is not False:
                c.execute(
                    "SELECT status, fail_count FROM api_keys WHERE id=?", (key_id,)
                )
                row = c.fetchone()
                if row is None:
                    return
                cur_status, fail_count = row[0] or "active", row[1] or 0
            new_status, fail_count, status_until = _next_key_state(
                cur_status, fail_count, kind
            )
            msg = (message or "")[:500]
            if _has_extended_key_columns is False:
                if new_status:
                    c.execute(
                        "UPDATE api_keys SET status=?, last_error=? WHERE id=?",
                        (new_status, msg, key_id),
                    )
            elif new_status == "active" and kind == "ok":
                c.execute(
                    "UPDATE api_keys SET status='active', last_error=NULL, "
                    "fail_count=0, status_until=0 WHERE id=?", (key_id,),
                )
            else:
                c.execute(
                    "UPDATE api_keys SET status=?, last_error=?, fail_count=?, "
                    "status_until=? WHERE id=?",
                    (new_status or cur_status, msg, fail_count, status_until, key_id),
                )
            conn.commit()
        except sqlite3.OperationalError:
            # 新列未迁移：退回旧写法
            try:
                new_status, _, _ = _next_key_state("active", 0, kind)
                if new_status:
                    conn.execute(
                        "UPDATE api_keys SET status=?, last_error=? WHERE id=?",
                        (new_status, (message or "")[:500], key_id),
                    )
                    conn.commit()
            except Exception:
                pass
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Resolve: step_name →候选 route 列表（首选 + 备选）
    # ------------------------------------------------------------------
    def resolve(self, step_name: str) -> _ResolvedRoute:
        """Resolve a strategy name to an upstream endpoint + credentials.

        保留旧签名：返回首选候选。备用候选见 :meth:`resolve_candidates`。
        """
        candidates = self.resolve_candidates(step_name)
        return candidates[0]

    def resolve_candidates(self, step_name: str) -> list[_ResolvedRoute]:
        """按「负载均衡首选 rule/ key → 其余 rule / key」顺序返回全部候选。

        与旧版差异：**不再因为某个 provider 没有 active key 就整体失败**。
        规则/provider/model 不可用、或某把 key 解密失败时只跳过该候选，
        仅当一个候选都构造不出来时才抛 DirectRouterError（消息含真实原因）。
        """
        strat = self._load_strategy(step_name)
        if not strat:
            raise DirectRouterError(
                f"DirectRouter: strategy '{step_name}' not found or inactive "
                f"(check router DB: strategies table)"
            )

        rules = strat.get("rules", [])
        if not rules:
            raise DirectRouterError(
                f"DirectRouter: no active rules for strategy '{step_name}'"
            )

        # 负载均衡选中的 rule 排最前，其余按 priority/id 顺序作为备选
        preferred = _select_rule(rules, strat["lb_strategy"], self._rr_index, strat["id"])
        if preferred:
            ordered_rules = [preferred] + [r for r in rules if r["id"] != preferred["id"]]
        else:
            ordered_rules = list(rules)

        candidates: list[_ResolvedRoute] = []
        skip_reasons: list[str] = []

        for rule in ordered_rules:
            provider = self._load_provider(rule["provider_id"])
            if not provider:
                skip_reasons.append(
                    f"provider_id={rule['provider_id']} not found or inactive"
                )
                continue

            model = self._load_model(rule["model_id"])
            if not model:
                skip_reasons.append(
                    f"model_id={rule['model_id']} not found or inactive"
                )
                continue

            keys = self._load_keys(provider["id"])
            if not keys:
                skip_reasons.append(
                    f"provider '{provider['name']}' has no API key configured"
                )
                continue

            for key in self._ordered_keys(keys):
                try:
                    real_key = _decrypt(key["key_value"])
                except Exception:
                    skip_reasons.append(
                        f"key #{key['id']} of '{provider['name']}' cannot be decrypted"
                    )
                    continue
                candidates.append(_ResolvedRoute(
                    strategy_id=strat["id"],
                    strategy_name=strat["name"],
                    timeout=strat.get("timeout") or 120,
                    retry_count=strat.get("retry_count") or 0,
                    rule_id=rule["id"],
                    provider_id=provider["id"],
                    provider_name=provider["name"],
                    provider_protocol=provider.get("protocol", "openai"),
                    provider_base_url=provider["base_url"].rstrip("/"),
                    model_id=model["id"],
                    model_model_id=model["model_id"],
                    model_display_name=model.get("display_name", ""),
                    api_key_id=key["id"],
                    api_key_decrypted=real_key,
                ))

        if not candidates:
            detail = "; ".join(dict.fromkeys(skip_reasons)) or "no usable rule/provider/key"
            raise DirectRouterError(
                f"DirectRouter: no usable route for strategy '{step_name}' ({detail})"
            )
        return candidates

    @staticmethod
    def _ordered_keys(keys: list[dict]) -> list[dict]:
        """可用 key 在前（active/untested、限流已冷却），其余兜底在后。"""
        now = time.time()
        usable = [k for k in keys if _key_usable(k, now)]
        rest = [k for k in keys if not _key_usable(k, now)]
        return usable + rest

    # ------------------------------------------------------------------
    # HTTP client pool
    # ------------------------------------------------------------------
    def _get_http_client(self, base_url: str, timeout: float) -> httpx.Client:
        key = (base_url, timeout)
        with self._http_lock:
            client = self._http_clients.get(key)
            if client is None:
                client = httpx.Client(
                    timeout=timeout,
                    trust_env=False,
                    transport=httpx.HTTPTransport(retries=2, trust_env=False),
                )
                self._http_clients[key] = client
            return client

    # ------------------------------------------------------------------
    # Build upstream request
    # ------------------------------------------------------------------
    @staticmethod
    def _build_upstream(route: _ResolvedRoute, request_body: dict,
                        is_stream: bool) -> tuple[str, dict, dict]:
        """Returns (url, headers, body) for the upstream request."""
        proto = route.provider_protocol
        base = route.provider_base_url

        if proto in ("openai", "custom"):
            url = f"{base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {route.api_key_decrypted}",
                "Content-Type": "application/json",
            }
            body = {**request_body, "model": route.model_model_id}
            if is_stream:
                body["stream"] = True
                body.setdefault("stream_options", {"include_usage": True})
            return url, headers, body

        if proto == "claude":
            url = f"{base}/messages"
            # Minimal OpenAI→Claude conversion
            msgs = request_body.get("messages", [])
            system_parts = []
            claude_msgs = []
            for m in msgs:
                if m.get("role") == "system":
                    system_parts.append(m.get("content", ""))
                else:
                    claude_msgs.append(m)
            claude_body: dict[str, Any] = {
                "model": route.model_model_id,
                "messages": claude_msgs,
                "max_tokens": request_body.get("max_tokens", 4096),
            }
            if system_parts:
                claude_body["system"] = "\n".join(system_parts)
            if is_stream:
                claude_body["stream"] = True
            headers = {
                "x-api-key": route.api_key_decrypted,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            return url, headers, claude_body

        if proto == "gemini":
            method = "streamGenerateContent" if is_stream else "generateContent"
            url = f"{base}/models/{route.model_model_id}:{method}?key={route.api_key_decrypted}"
            # Minimal OpenAI→Gemini conversion
            msgs = request_body.get("messages", [])
            contents = []
            for m in msgs:
                role = "user" if m.get("role") != "assistant" else "model"
                parts = [{"text": m.get("content", "")}]
                contents.append({"role": role, "parts": parts})
            gemini_body: dict[str, Any] = {"contents": contents}
            gen_config: dict[str, Any] = {}
            if "max_tokens" in request_body:
                gen_config["maxOutputTokens"] = request_body["max_tokens"]
            if "temperature" in request_body:
                gen_config["temperature"] = request_body["temperature"]
            if gen_config:
                gemini_body["generationConfig"] = gen_config
            headers = {"content-type": "application/json"}
            return url, headers, gemini_body

        # Fallback: treat as openai-compatible
        url = f"{base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {route.api_key_decrypted}",
            "Content-Type": "application/json",
        }
        body = {**request_body, "model": route.model_model_id}
        if is_stream:
            body["stream"] = True
        return url, headers, body

    # ------------------------------------------------------------------
    # Log request to router DB
    # ------------------------------------------------------------------
    def _log_request(self, route: _ResolvedRoute, request_body: dict,
                     status_code: int, latency_ms: int, is_stream: bool,
                     error_message: str | None,
                     prompt_tokens: int = 0, completion_tokens: int = 0):
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO request_logs "
                "(strategy_id, provider_id, api_key_id, model_used, request_body, "
                "status_code, latency_ms, is_stream, prompt_tokens, completion_tokens, "
                "total_tokens, error_message) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    route.strategy_id, route.provider_id, route.api_key_id,
                    route.model_model_id,
                    json.dumps(request_body, ensure_ascii=False)[:2000],
                    status_code, latency_ms, is_stream,
                    prompt_tokens, completion_tokens,
                    prompt_tokens + completion_tokens,
                    error_message,
                ),
            )
            conn.commit()
        except Exception:
            pass  # log failure should not break the request
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Parse upstream response (basic protocol conversion)
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_response(resp: httpx.Response, route: _ResolvedRoute) -> dict:
        """Parse upstream response and convert to OpenAI format if needed."""
        data = resp.json()
        proto = route.provider_protocol

        if proto == "claude":
            # Claude → OpenAI minimal conversion
            content_blocks = data.get("content", [])
            text = "".join(
                b.get("text", "") for b in content_blocks if b.get("type") == "text"
            )
            usage = data.get("usage", {})
            return {
                "id": data.get("id", ""),
                "object": "chat.completion",
                "model": route.model_model_id,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": data.get("stop_reason", "stop"),
                }],
                "usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                },
            }

        if proto == "gemini":
            # Gemini → OpenAI minimal conversion
            candidates = data.get("candidates", [])
            text = ""
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
            usage = data.get("usageMetadata", {})
            return {
                "id": "",
                "object": "chat.completion",
                "model": route.model_model_id,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }],
                "usage": {
                    "prompt_tokens": usage.get("promptTokenCount", 0),
                    "completion_tokens": usage.get("candidatesTokenCount", 0),
                    "total_tokens": usage.get("totalTokenCount", 0),
                },
            }

        # openai / custom: pass through
        return data

    # ------------------------------------------------------------------
    # Forward: the main entry point
    # ------------------------------------------------------------------
    def forward(self, step_name: str, request_body: dict,
                timeout: float | None = None, is_stream: bool = False) -> dict:
        """Resolve strategy and forward request directly to upstream.

        逐个尝试候选 route（rule × key），实现真正的 failover：
        - key 级问题（429 限流 / 401、403 鉴权失败）→ 换同 provider 的下一把 key；
        - 连不通（DNS/拒连/TLS/超时）→ 换下一个 provider（key 状态保持不变）；
        - 其它 4xx（模型/参数错）与上游 5xx → 不重试，直接抛出真实错误。

        日志仍写入 request_logs；key 状态按失败类型更新（连不通不弃用）。
        """
        candidates = self.resolve_candidates(step_name)
        # 候选上限：规则数 × 每规则 key 数，额外留一次重试余量
        max_tries = min(len(candidates) + 1, 8)
        failed_keys: set = set()
        failed_providers: set = set()
        last_error: Exception | None = None

        for route in candidates[:max_tries]:
            if route.api_key_id in failed_keys or route.provider_id in failed_providers:
                continue

            effective_timeout = timeout or route.timeout or 120
            url, headers, body = self._build_upstream(route, request_body, is_stream)
            client = self._get_http_client(route.provider_base_url, effective_timeout)

            t0 = time.time()
            try:
                resp = client.post(url, headers=headers, json=body)
            except Exception as e:
                latency = int((time.time() - t0) * 1000)
                kind = _classify_exception(e)  # unreachable：连不通，不弃用 key
                self._update_key_state(route.api_key_id, kind, str(e))
                self._log_request(route, request_body, 502, latency, is_stream, str(e)[:500])
                print(
                    f"[DirectRouter] {route.strategy_name}: provider="
                    f"{route.provider_name} key=#{route.api_key_id} "
                    f"{kind} ({str(e)[:120]}) → 尝试下一个候选",
                    flush=True,
                )
                failed_keys.add(route.api_key_id)
                failed_providers.add(route.provider_id)
                last_error = e
                continue

            latency = int((time.time() - t0) * 1000)
            status = resp.status_code

            if status in (401, 403, 429):
                kind = _classify_status(status)
                self._update_key_state(route.api_key_id, kind, f"HTTP {status}")
                self._log_request(route, request_body, status, latency, is_stream, resp.text[:500])
                print(
                    f"[DirectRouter] {route.strategy_name}: provider="
                    f"{route.provider_name} key=#{route.api_key_id} HTTP {status}"
                    f"（{kind}）→ 跳过该 key 继续",
                    flush=True,
                )
                failed_keys.add(route.api_key_id)
                try:
                    resp.raise_for_status()
                except Exception as e:
                    last_error = e
                continue

            if status >= 400:
                self._log_request(route, request_body, status, latency, is_stream, resp.text[:500])
                resp.raise_for_status()  # 非key 级错误：直接抛真实错误

            # 成功：复位 key 状态
            self._update_key_state(route.api_key_id, "ok", "")
            data = self._parse_response(resp, route)
            usage = data.get("usage", {})
            self._log_request(
                route, request_body, 200, latency, is_stream, None,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )
            return data

        if last_error is not None:
            raise last_error
        raise DirectRouterError(
            f"DirectRouter: all routes failed for strategy '{step_name}' "
            f"(no reachable key/provider)"
        )


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------
_direct_router: DirectRouter | None = None
_direct_router_lock = threading.Lock()


def get_direct_router() -> DirectRouter:
    global _direct_router
    if _direct_router is None:
        with _direct_router_lock:
            if _direct_router is None:
                _direct_router = DirectRouter()
    return _direct_router
