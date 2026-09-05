"""
Unified LLM client. All requests go through a single base_url,
with the step name used as the model name for routing.
Supports: concurrent requests, timeout, streaming, conversation history.
"""
import base64
import json
import os
import time
import threading
from typing import Any, List, Optional, Generator
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from openai import OpenAI

from backend.config.config_manager import config

LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "output", "llm_logs"
)


class LLMErrorType:
    """LLM 错误分类。决定错误是否可重试，并在日志中精确标注错误来源。

    只有传输类错误（超时/连接/限流/上游5xx）才会重试；鉴权、参数、解析、
    配置等错误重试必然复现，必须立即抛出真实错误，避免无意义的反复重试。
    """
    TIMEOUT = "timeout"          # 请求超时（可重试）
    CONNECTION = "connection"    # 连接失败/对端断开等传输错误（可重试）
    RATE_LIMIT = "rate_limit"    # 429 限流（可重试）
    SERVER = "server"            # 上游 5xx（可重试）
    AUTH = "auth"                # 401/403 鉴权失败（不重试）
    QUOTA = "quota"              # 402 余额/配额不足（不重试）
    BAD_REQUEST = "bad_request"  # 400/404/413/422 等，如 prompt 超长（不重试）
    PARSE = "parse"              # 请求成功但响应内容解析失败（不重试）
    CONFIG = "config"            # 本地配置缺失（不重试）
    UNKNOWN = "unknown"          # 其他未知错误（不重试，直接暴露真实错误）


RETRYABLE_ERROR_TYPES = {
    LLMErrorType.TIMEOUT,
    LLMErrorType.CONNECTION,
    LLMErrorType.RATE_LIMIT,
    LLMErrorType.SERVER,
}


class LLMRequestError(RuntimeError):
    """带分类的 LLM 请求异常。

    - error_type / retryable：调用方可据此决定是否重试，非 LLM 传输错误不会被重试
    - message 保留上游/本地真实错误原文，便于直接定位
    """

    def __init__(self, message: str, error_type: str = LLMErrorType.UNKNOWN,
                 status_code: Optional[int] = None,
                 step: Optional[str] = None, model: Optional[str] = None):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code
        self.step = step
        self.model = model

    @property
    def retryable(self) -> bool:
        return self.error_type in RETRYABLE_ERROR_TYPES


# --- 复用 OpenAI 客户端连接池：按 (base_url, api_key, timeout) 缓存单例 ---
_CLIENT_CACHE: dict = {}
_CLIENT_CACHE_LOCK = threading.Lock()
_CLIENT_CACHE_MAX = 8

# --- 日志写入锁（JSONL 追加写） ---
_LOG_LOCK = threading.Lock()

class LLMClient:
    """Unified LLM request client with step-name-based model routing."""

    def __init__(self):
        pass

    def _get_llm_config_snapshot(self) -> dict:
        """读取整个 llm 配置子树（一次 YAML 加载），避免每次请求多次 reload。"""
        return config.get("llm") or {}

    def _get_api_config(self, step_name: str) -> dict:
        """读取配置（单次快照）以决定路由/base_url/model/timeout/retry。"""
        llm_cfg = self._get_llm_config_snapshot()
        use_router = llm_cfg.get("use_router")
        if use_router:
            base_url = llm_cfg.get("router_url") or "http://localhost:8800/v1"
            api_key = llm_cfg.get("router_api_key") or "123"
        else:
            base_url = llm_cfg.get("base_url") or ""
            api_key = llm_cfg.get("api_key") or ""
        timeout = llm_cfg.get("timeout") or 120
        retry_enabled = llm_cfg.get("retry_enabled")
        if retry_enabled is None:
            retry_enabled = True
        retry_count = llm_cfg.get("retry_count") or 1

        step_models = llm_cfg.get("step_models") or {}
        default_model = step_models.get("default_model") or ""
        enable_step_models = llm_cfg.get("enable_step_models")
        if enable_step_models is False:
            model = default_model or step_name
        else:
            model = step_models.get(step_name) or default_model or step_name

        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "timeout": timeout,
            "retry_enabled": retry_enabled,
            "retry_count": retry_count,
        }

    def _make_client(self, api_cfg: dict) -> OpenAI:
        """Create (or reuse from cache) an OpenAI client with timeout.

        复用连接池：相同 (base_url, api_key, timeout) 的 client 只创建一次，
        避免每个请求重复 TCP+TLS 握手。
        """
        url = api_cfg["base_url"]
        # 去除用户可能多填的 /chat/completions 结尾
        lower = url.lower()
        if lower.endswith("/v1/chat/completions"):
            url = url[: -len("/chat/completions")]
        elif lower.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        url = url.rstrip("/")
        timeout_val = float(api_cfg.get("timeout", 120))
        key = (url, api_cfg["api_key"], timeout_val)
        with _CLIENT_CACHE_LOCK:
            client = _CLIENT_CACHE.get(key)
            if client is None:
                client = OpenAI(
                    api_key=api_cfg["api_key"],
                    base_url=url,
                    timeout=timeout_val,
                    max_retries=0,
                    # 忽略系统代理（VPN 全局代理会设置 HTTP_PROXY/HTTPS_PROXY），直接连接上游，避免 502
                    # transport 启用连接级重试：复用连接池时若上游已关闭空闲 keep-alive 连接
                    # （表现为 ConnectionResetError / WinError 10054），httpx 会换新连接重试
                    http_client=httpx.Client(
                        timeout=timeout_val,
                        trust_env=False,
                        transport=httpx.HTTPTransport(retries=3, trust_env=False),
                    ),
                )
                _CLIENT_CACHE[key] = client
                # 简单上限保护：超出时丢弃最早的缓存，避免无限堆积
                if len(_CLIENT_CACHE) > _CLIENT_CACHE_MAX:
                    _CLIENT_CACHE.pop(next(iter(_CLIENT_CACHE)))
            return client

    # --- 错误分类 -----------------------------------------------------------
    #
    # 只依据异常类型与 HTTP 状态码归类，不对错误文本做宽泛子串匹配。
    # 旧版用 "timeout"/"502"/"连接被" 等文本猜测可重试性，会把 prompt 构建、
    # 响应处理等非 LLM 传输错误误判为请求失败而反复重试，掩盖真实错误。

    # 异常类名 → 分类（同时检查 __cause__ 链，覆盖 OpenAI SDK/httpx 的包装异常）
    _TIMEOUT_NAMES = {
        "APITimeoutError", "TimeoutError", "ReadTimeout",
        "ConnectTimeout", "WriteTimeout", "PoolTimeout",
    }
    _CONN_NAMES = {
        "APIConnectionError", "ConnectError", "ConnectionError",
        "ConnectionResetError", "ConnectionAbortedError", "ConnectionRefusedError",
        "RemoteDisconnected", "RemoteProtocolError", "ReadError", "WriteError",
        "TransportError", "SSLError",
    }

    @staticmethod
    def _extract_status(exc: Exception) -> Optional[int]:
        """从异常或其 response 属性中提取 HTTP 状态码（OpenAI SDK/httpx 均适用）。"""
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            return status
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
        return status if isinstance(status, int) else None

    @classmethod
    def _classify_error(cls, exc: Exception) -> tuple:
        """返回 (error_type, http_status)。error_type 决定是否可重试。"""
        status = cls._extract_status(exc)
        names = {type(exc).__name__}
        cause = getattr(exc, "__cause__", None)
        if cause is not None:
            names.add(type(cause).__name__)
        if names & cls._TIMEOUT_NAMES:
            return LLMErrorType.TIMEOUT, status
        if names & cls._CONN_NAMES:
            return LLMErrorType.CONNECTION, status
        if isinstance(status, int):
            if status == 408:
                return LLMErrorType.TIMEOUT, status
            if status == 429:
                return LLMErrorType.RATE_LIMIT, status
            if status in (401, 403):
                return LLMErrorType.AUTH, status
            if status == 402:
                return LLMErrorType.QUOTA, status
            if 400 <= status < 500:
                return LLMErrorType.BAD_REQUEST, status
            if status >= 500:
                return LLMErrorType.SERVER, status
        # 未知错误（响应结构异常、本地处理出错等）一律不重试，直接抛真实错误
        return LLMErrorType.UNKNOWN, status

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """兼容旧调用：错误是否属于可重试的 LLM 传输类错误。"""
        err_type, _ = LLMClient._classify_error(exc)
        return err_type in RETRYABLE_ERROR_TYPES

    @staticmethod
    def _parse_response_content(content: str, response_json: bool) -> Any:
        if not response_json:
            return content
        try:
            import json_repair

            return json_repair.loads(content)
        except Exception:
            return json.loads(content)

    def _save_log(self, step_name: str, prompt: str, response: Any):
        os.makedirs(LOG_DIR, exist_ok=True)
        # 改为 JSONL 追加写：单条一行，避免每次请求全量读改写整个 JSON 文件
        log_file = os.path.join(LOG_DIR, f"{step_name}.jsonl")
        entry = {
            "prompt": str(prompt)[:500],
            "response": str(response)[:500],
            "time": time.time(),
        }
        try:
            line = json.dumps(entry, ensure_ascii=False)
            with _LOG_LOCK:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    def chat(
        self,
        step_name: str,
        prompt: str,
        messages: Optional[list] = None,
        response_json: bool = True,
        stream: bool = False,
        log: bool = True,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        images: Optional[List[str]] = None,
        log_request_params: bool = False,
    ) -> Any:
        """
        Send a chat completion request.

        Args:
            step_name: Used as model name (or looks up step_models override).
            prompt: User prompt string.
            messages: Optional full message history (overrides prompt).
            response_json: Request JSON response format.
            stream: Enable streaming response.
            log: Save request/response log.
            system_prompt: Optional system message prepended to conversation.
            temperature: Override temperature (None = API default).
            images: Optional list of image file paths for multimodal requests.
            log_request_params: Print full request parameters before sending.

        Returns:
            Parsed response (dict if response_json, str otherwise).
            If stream=True, returns a generator of text chunks.
        """
        api_cfg = self._get_api_config(step_name)
        if not api_cfg["base_url"] or not api_cfg["api_key"]:
            # 配置缺失是本地问题，重试无意义，直接给出可定位的错误
            raise LLMRequestError(
                f"LLM config incomplete: base_url={api_cfg['base_url']!r}, "
                "please configure in Settings > LLM",
                error_type=LLMErrorType.CONFIG, step=step_name, model=api_cfg.get("model"),
            )

        # Build message list
        if messages:
            msg_list = messages[:]
        else:
            msg_list = []
            if system_prompt:
                msg_list.append({"role": "system", "content": system_prompt})
            # Build user content (multimodal if images provided)
            if images:
                user_content = [{"type": "text", "text": prompt}]
                for img_path in images:
                    if os.path.exists(img_path):
                        with open(img_path, "rb") as f:
                            b64 = base64.b64encode(f.read()).decode("utf-8")
                        ext = os.path.splitext(img_path)[1].lower().lstrip(".")
                        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}.get(ext, "jpeg")
                        user_content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{mime};base64,{b64}"},
                        })
                msg_list.append({"role": "user", "content": user_content})
            else:
                msg_list.append({"role": "user", "content": prompt})

        client = self._make_client(api_cfg)
        step_model = api_cfg["model"]
        timeout_val = api_cfg.get("timeout", 120)

        kwargs = {
            "model": step_model,
            "messages": msg_list,
        }
        if response_json and not stream:
            kwargs["response_format"] = {"type": "json_object"}
        if temperature is not None:
            kwargs["temperature"] = temperature

        if log_request_params:
            _log_parts = [
                f"[LLM Request Params]",
                f"  model: {step_model}",
                f"  response_json: {response_json}",
                f"  stream: {stream}",
                f"  temperature: {kwargs.get('temperature', 'default')}",
                f"  images: {len(images) if images else 0} file(s)",
                f"  messages ({len(msg_list)}):",
            ]
            for m in msg_list:
                role = m.get("role", "?")
                content = m.get("content", "")
                if isinstance(content, list):
                    text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                    img_count = sum(1 for p in content if p.get("type") == "image_url")
                    _log_parts.append(f"    [{role}] text: {' '.join(text_parts)[:300]}, images: {img_count}")
                else:
                    _log_parts.append(f"    [{role}] {str(content)[:300]}")
            print("\n".join(_log_parts), flush=True)

        # 请求元信息一行日志：排查超时/路由问题时，可确认实际生效的
        # base_url、model、超时时间与请求体量（多模态图片不计入字符数）
        prompt_chars = 0
        for m in msg_list:
            c = m.get("content", "")
            if isinstance(c, str):
                prompt_chars += len(c)
            else:
                prompt_chars += sum(
                    len(p.get("text", "")) for p in c if isinstance(p, dict) and p.get("type") == "text"
                )
        print(
            f"[LLM] request (step={step_name}, model={step_model}, stream={stream}, "
            f"response_json={response_json}, timeout={timeout_val}s, "
            f"prompt_chars={prompt_chars}, base_url={api_cfg['base_url']})",
            flush=True,
        )

        if stream:
            return self._stream_response(client, kwargs, step_name, prompt, log)

        # Retry loop: ONLY transport-level errors (timeout / connection / 429 / 5xx)
        # are retried. All other errors (auth, bad request, parse failure, config,
        # unknown) raise immediately with the real cause — retrying them cannot
        # succeed and only masks the actual problem.
        retry_enabled = api_cfg.get("retry_enabled", True)
        retry_count = api_cfg.get("retry_count", 1) if retry_enabled else 0

        last_error = None
        for attempt in range(retry_count + 1):
            t0 = time.time()
            try:
                resp = client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content or ""
                # Parse the response separately: a parse failure means the request
                # SUCCEEDED but the returned content is invalid (e.g. not JSON).
                # Attribute it precisely instead of masking it as "request failed",
                # and do NOT retry (retrying yields the same unparseable content).
                try:
                    result = self._parse_response_content(content, response_json)
                except Exception as parse_err:
                    print(
                        f"[LLM] parse failed, NOT retryable (step={step_name}, "
                        f"model={step_model}): {parse_err}",
                        flush=True,
                    )
                    raise LLMRequestError(
                        f"LLM response parse failed (step={step_name}, model={step_model}): {parse_err}",
                        error_type=LLMErrorType.PARSE, step=step_name, model=step_model,
                    ) from parse_err
                if log:
                    self._save_log(step_name, prompt, result)
                print(
                    f"[LLM] ok (step={step_name}, model={step_model}, "
                    f"elapsed={time.time() - t0:.1f}s)",
                    flush=True,
                )
                return result
            except LLMRequestError:
                raise  # 已分类错误（解析失败等）不再进入重试
            except Exception as e:
                err_type, status = self._classify_error(e)
                elapsed = time.time() - t0
                if err_type in RETRYABLE_ERROR_TYPES:
                    last_error = e
                    if attempt < retry_count:
                        wait = 3 * (attempt + 1)
                        print(
                            f"[LLM] {err_type} (step={step_name}, model={step_model}), "
                            f"attempt {attempt + 1}/{retry_count + 1}, "
                            f"elapsed {elapsed:.1f}s, status={status}, retrying in {wait}s...",
                            flush=True,
                        )
                        time.sleep(wait)
                        continue
                    break  # 可重试错误但重试已耗尽，落到最终报错
                # 不可重试错误：立即抛出真实错误（保留上游错误原文），绝不重复重试
                print(
                    f"[LLM] {err_type} NOT retryable (step={step_name}, model={step_model}, "
                    f"status={status}, elapsed={elapsed:.1f}s): {str(e)[:300]}",
                    flush=True,
                )
                raise LLMRequestError(
                    f"LLM request failed (step={step_name}, model={step_model}, "
                    f"type={err_type}, status={status}): {e}",
                    error_type=err_type, status_code=status, step=step_name, model=step_model,
                ) from e

        # All retries exhausted
        if last_error is not None:
            err_type, status = self._classify_error(last_error)
            raise LLMRequestError(
                f"LLM request failed after {retry_count + 1} attempts "
                f"(step={step_name}, model={step_model}, type={err_type}, status={status}): {last_error}",
                error_type=err_type, status_code=status, step=step_name, model=step_model,
            ) from last_error

    def _stream_response(
        self, client: OpenAI, kwargs: dict, step_name: str, prompt: str, log: bool
    ) -> Generator[str, None, None]:
        """Stream response chunks."""
        kwargs["stream"] = True
        resp = client.chat.completions.create(**kwargs)
        full_content = ""
        for chunk in resp:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                full_content += delta.content
                yield delta.content
        if log:
            self._save_log(step_name, prompt, full_content)

    def batch_chat(
        self,
        requests: list[dict],
        max_workers: Optional[int] = None,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> list[Any]:
        """
        Execute multiple LLM requests concurrently with retry support.

        Args:
            requests: List of dicts with keys: step_name, prompt, and optional params.
            max_workers: Override concurrent limit.
            max_retries: Maximum number of retries for failed requests (default: 3).
            retry_delay: Initial delay between retries in seconds (default: 2.0).

        Returns:
            List of results in same order as requests.
        """
        if not requests:
            return []

        # 读取配置快照（一次），避免重复 reload 整个 YAML
        llm_cfg = config.get("llm") or {}
        # 兼容旧 key：llm.api.timeout 优先于 llm.timeout
        timeout_per_request = float(
            llm_cfg.get("api.timeout") or llm_cfg.get("timeout") or 180
        )

        def _execute_single_request(req: dict, step: str) -> Any:
            """Execute a single request with retry logic."""
            import time

            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    result = self.chat(
                        step,
                        req.get("prompt", ""),
                        messages=req.get("messages"),
                        response_json=req.get("response_json", True),
                        stream=req.get("stream", False),
                        log=req.get("log", False),
                        system_prompt=req.get("system_prompt"),
                        temperature=req.get("temperature"),
                        images=req.get("images"),
                        log_request_params=req.get("log_request_params", False),
                    )
                    return result
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    # 仅重试可重试的 LLM 传输类错误（超时/连接/限流/上游5xx）；
                    # 鉴权、参数、解析、配置等错误重试必然复现，立即抛出真实错误
                    err_type = getattr(e, "error_type", None)
                    if err_type is not None:
                        is_transient = err_type in RETRYABLE_ERROR_TYPES
                    else:
                        is_transient = LLMClient._is_retryable_error(e)
                    if attempt < max_retries and is_transient:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                        print(
                            f"[LLM] 请求失败 (step={step}, attempt {attempt + 1}/{max_retries + 1}), "
                            f"{wait_time:.1f}s 后重试: {error_str[:120]}"
                        )
                        time.sleep(wait_time)
                    else:
                        # Non-transient error or max retries reached
                        if not is_transient:
                            print(
                                f"[LLM] non-retryable, fail fast (step={step}): {error_str[:200]}",
                                flush=True,
                            )
                        raise

        # Always use a fresh local executor to avoid stale/shut-down executor issues
        max_workers = max_workers or max(1, int(llm_cfg.get("max_concurrent") or 10))
        max_workers = max(1, int(max_workers))
        executor = ThreadPoolExecutor(max_workers=max_workers)
        futures = {}
        results = [None] * len(requests)

        try:
            try:
                for i, req in enumerate(requests):
                    step = req.get("step_name", "batch")
                    future = executor.submit(
                        _execute_single_request,
                        req,
                        step,
                    )
                    futures[future] = i
            except RuntimeError as e:
                # Interpreter shutting down — fall back to sequential execution
                if "interpreter shutdown" in str(e) or "cannot schedule" in str(e):
                    print("[LLM] 解释器正在关闭，回退到顺序执行...")
                    executor.shutdown(wait=False)
                    for i, req in enumerate(requests):
                        if results[i] is None:
                            try:
                                step = req.get("step_name", "batch")
                                results[i] = _execute_single_request(req, step)
                            except Exception as ex:
                                results[i] = {"error": str(ex)}
                    return results
                raise

            for future in as_completed(futures, timeout=timeout_per_request * (max_retries + 1)):
                idx = futures[future]
                try:
                    results[idx] = future.result(timeout=5)
                except Exception as e:
                    results[idx] = {"error": str(e)}
        except TimeoutError:
            print(f"[LLM] Batch processing timed out after {timeout_per_request * (max_retries + 1)}s")
            # Cancel remaining futures
            for future in futures:
                if not future.done():
                    future.cancel()
            # Fill in timeout errors for unfinished requests
            for i, result in enumerate(results):
                if result is None:
                    results[i] = {"error": f"Request timed out after {timeout_per_request}s"}
        finally:
            executor.shutdown(wait=False)

        return results


# Singleton
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
