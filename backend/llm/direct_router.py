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


def _select_key(keys: list[dict]) -> dict | None:
    active = [k for k in keys if k.get("status") in ("active", "untested")]
    if active:
        return active[0]
    return keys[0] if keys else None


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
        conn = _get_conn()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT id, provider_id, key_value, status, weight "
                "FROM api_keys WHERE provider_id=? AND status IN ('active','untested') "
                "ORDER BY id",
                (provider_id,),
            )
            return [_row_to_dict(r) for r in c.fetchall()]
        finally:
            conn.close()

    def _update_key_status(self, key_id: int, status: str, error: str = ""):
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE api_keys SET status=?, last_error=? WHERE id=?",
                (status, error[:500], key_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Resolve: step_name → _ResolvedRoute
    # ------------------------------------------------------------------
    def resolve(self, step_name: str) -> _ResolvedRoute:
        """Resolve a strategy name to an upstream endpoint + credentials.

        Raises ValueError with a descriptive message on failure
        (strategy not found, no active rules, provider inactive, etc.).
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

        # Select rule
        rule = _select_rule(rules, strat["lb_strategy"], self._rr_index, strat["id"])
        if not rule:
            raise DirectRouterError(
                f"DirectRouter: balancer returned no rule for '{step_name}'"
            )

        # Load provider
        provider = self._load_provider(rule["provider_id"])
        if not provider:
            raise DirectRouterError(
                f"DirectRouter: provider_id={rule['provider_id']} not found or inactive "
                f"(for strategy '{step_name}')"
            )

        # Load model
        model = self._load_model(rule["model_id"])
        if not model:
            raise DirectRouterError(
                f"DirectRouter: model_id={rule['model_id']} not found or inactive "
                f"(for strategy '{step_name}', provider '{provider['name']}')"
            )

        # Select API key
        keys = self._load_keys(provider["id"])
        if not keys:
            raise DirectRouterError(
                f"DirectRouter: no active API key for provider '{provider['name']}' "
                f"(strategy '{step_name}')"
            )
        key = _select_key(keys)
        real_key = _decrypt(key["key_value"])

        return _ResolvedRoute(
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
        )

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

        Returns OpenAI-format response dict. Raises on failure
        (network error, upstream error, resolution error).

        Logs to request_logs and updates key status on auth/rate errors.
        """
        route = self.resolve(step_name)
        effective_timeout = timeout or route.timeout or 120

        url, headers, body = self._build_upstream(route, request_body, is_stream)
        client = self._get_http_client(route.provider_base_url, effective_timeout)

        t0 = time.time()
        try:
            resp = client.post(url, headers=headers, json=body)
        except Exception as e:
            latency = int((time.time() - t0) * 1000)
            self._log_request(route, request_body, 502, latency, is_stream, str(e)[:500])
            raise

        latency = int((time.time() - t0) * 1000)

        if resp.status_code == 429:
            self._update_key_status(route.api_key_id, "rate_limited", "Rate limited")
            self._log_request(route, request_body, 429, latency, is_stream, resp.text[:500])
            resp.raise_for_status()

        if resp.status_code in (401, 403):
            self._update_key_status(route.api_key_id, "inactive", f"Auth error: {resp.status_code}")
            self._log_request(route, request_body, resp.status_code, latency, is_stream, resp.text[:500])
            resp.raise_for_status()

        if resp.status_code >= 400:
            self._log_request(route, request_body, resp.status_code, latency, is_stream, resp.text[:500])
            resp.raise_for_status()

        # Success: parse and log
        data = self._parse_response(resp, route)
        usage = data.get("usage", {})
        self._log_request(
            route, request_body, 200, latency, is_stream, None,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        return data


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
