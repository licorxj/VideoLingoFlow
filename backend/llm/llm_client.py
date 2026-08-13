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

class LLMClient:
    """Unified LLM request client with step-name-based model routing."""

    def __init__(self):
        pass

    def _get_api_config(self, step_name: str) -> dict:
        """Read config on every call (live update support)."""
        use_router = config.get("llm.use_router")
        if use_router:
            base_url = config.get("llm.router_url") or "http://localhost:8800/v1"
            api_key = config.get("llm.router_api_key") or "123"
        else:
            base_url = config.get("llm.base_url") or ""
            api_key = config.get("llm.api_key") or ""
        timeout = config.get("llm.timeout") or 120
        retry_enabled = config.get("llm.retry_enabled")
        if retry_enabled is None:
            retry_enabled = True
        retry_count = config.get("llm.retry_count") or 1

        # Check for step-specific model override
        # Priority: exact step override > default_model > step_name
        step_override = config.get(f"llm.step_models.{step_name}")
        default_model = config.get("llm.step_models.default_model") or ""
        model = step_override or default_model or step_name

        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "timeout": timeout,
            "retry_enabled": retry_enabled,
            "retry_count": retry_count,
        }

    def _make_client(self, api_cfg: dict) -> OpenAI:
        """Create an OpenAI client with timeout."""
        url = api_cfg["base_url"]
        # 去除用户可能多填的 /chat/completions 结尾
        lower = url.lower()
        if lower.endswith("/v1/chat/completions"):
            url = url[: -len("/chat/completions")]
        elif lower.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        url = url.rstrip("/")
        timeout_val = api_cfg.get("timeout", 120)
        return OpenAI(
            api_key=api_cfg["api_key"],
            base_url=url,
            timeout=float(timeout_val),
            max_retries=0,
            # 忽略系统代理（VPN 全局代理会设置 HTTP_PROXY/HTTPS_PROXY），直接连接上游，避免 502
            http_client=httpx.Client(timeout=float(timeout_val), trust_env=False),
        )

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        """Best-effort timeout detection across OpenAI/httpx error types."""
        exc_names = {type(exc).__name__}
        cause = getattr(exc, "__cause__", None)
        if cause:
            exc_names.add(type(cause).__name__)
        if {"APITimeoutError", "TimeoutError", "ReadTimeout", "ConnectTimeout"} & exc_names:
            return True
        text = str(exc).lower()
        return "timed out" in text or "timeout" in text

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """Check if error is retryable: timeout or 5xx server errors."""
        # Timeout errors
        if LLMClient._is_timeout_error(exc):
            return True
        # 5xx server errors (502, 503, 504, etc.)
        exc_names = {type(exc).__name__}
        cause = getattr(exc, "__cause__", None)
        if cause:
            exc_names.add(type(cause).__name__)
        if {"InternalServerError", "APIStatusError"} & exc_names:
            return True
        status_code = getattr(exc, "status_code", None)
        if status_code and 500 <= status_code < 600:
            return True
        text = str(exc).lower()
        return "error code: 5" in text or "502" in text or "503" in text or "504" in text

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
        log_file = os.path.join(LOG_DIR, f"{step_name}.json")
        entry = {
            "prompt": str(prompt)[:500],
            "response": str(response)[:500],
            "time": time.time(),
        }
        try:
            if os.path.exists(log_file):
                with open(log_file, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            else:
                logs = []
            logs.append(entry)
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(logs[-200:], f, ensure_ascii=False, indent=2)
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
            raise ValueError(
                f"LLM config incomplete: base_url={api_cfg['base_url']!r}, "
                "please configure in Settings > LLM"
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

        if stream:
            return self._stream_response(client, kwargs, step_name, prompt, log)

        # Retry loop for timeout and server errors (config-driven)
        retry_enabled = api_cfg.get("retry_enabled", True)
        retry_count = api_cfg.get("retry_count", 1) if retry_enabled else 0

        last_error = None
        for attempt in range(retry_count + 1):
            try:
                resp = client.chat.completions.create(**kwargs)
                content = resp.choices[0].message.content or ""
                result = self._parse_response_content(content, response_json)
                if log:
                    self._save_log(step_name, prompt, result)
                return result
            except Exception as e:
                if self._is_retryable_error(e):
                    last_error = e
                    if attempt < retry_count:
                        wait = 3 * (attempt + 1)
                        err_type = "Timeout" if self._is_timeout_error(e) else f"Server error ({e})"
                        print(
                            f"[LLM] {err_type} (step={step_name}, model={step_model}), "
                            f"attempt {attempt + 1}/{retry_count + 1}, retrying in {wait}s...",
                            flush=True,
                        )
                        time.sleep(wait)
                    continue
                # Non-retryable errors raise immediately
                raise RuntimeError(
                    f"LLM request failed (step={step_name}, model={step_model}): {e}"
                ) from e

        # All retries exhausted
        err_type = "Timeout" if self._is_timeout_error(last_error) else f"Server error"
        raise RuntimeError(
            f"LLM request failed after {retry_count + 1} attempts: {err_type} "
            f"(step={step_name}, model={step_model})"
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

        # Get timeout from config, default to 180 seconds per request
        timeout_per_request = float(config.get("llm.api.timeout") or 180)

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
                    # Only retry on transient errors (502, 503, 504, timeout, connection errors)
                    is_transient = any(code in error_str for code in ["502", "503", "504", "timeout", "Timeout", "Connection"])
                    if attempt < max_retries and is_transient:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                        print(f"[LLM] 请求失败 (attempt {attempt + 1}/{max_retries + 1}), {wait_time:.1f}s 后重试: {error_str[:100]}")
                        time.sleep(wait_time)
                    else:
                        # Non-transient error or max retries reached
                        raise

        # Always use a fresh local executor to avoid stale/shut-down executor issues
        max_workers = max_workers or max(1, int(config.get("llm.max_concurrent") or 10))
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
