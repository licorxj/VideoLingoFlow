#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生图接口共享的网络层重试工具（同步 requests）。

仅对「传输层瞬断」重试（连接错误 / 超时 / 分块中断 / 解码错误），
不对「HTTP 业务错误」（4xx/5xx，由 resp.raise_for_status() 抛 HTTPError）重试——
因为那代表确定性的服务端拒绝，重试无意义。

设计目标：与 kieai_sdk 的异步重试保持一致，让所有生图接口在弱网下
（一次抖动）不至于直接丢结果，而是退避重试几次。
"""
import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

# 视为「瞬断、可重试」的 requests 异常（不含 HTTPError：那是确定性业务错误）。
_RETRYABLE = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ContentDecodingError,
)

DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 1.0


def request_with_retry(method: str, url: str, *, retries: int = DEFAULT_RETRIES,
                       backoff: float = DEFAULT_BACKOFF, **kwargs) -> "requests.Response":
    """``requests.request`` 的带重试封装。

    - 仅对传输层瞬断重试（指数退避 1s→2s→4s…）；
    - HTTP 业务错误（``raise_for_status`` 抛 ``HTTPError``）直接上抛，不重试；
    - 调用方负责 ``resp.raise_for_status()`` 与解析响应体。
    返回最后一次成功的 ``requests.Response``。
    """
    last = None
    for attempt in range(max(1, retries)):
        try:
            return requests.request(method, url, **kwargs)
        except _RETRYABLE as e:
            last = e
            if attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                logger.warning("网络瞬断，%ss 后重试 (%d/%d): %s",
                               wait, attempt + 1, retries, e)
                time.sleep(wait)
                continue
    raise last


def download_with_retry(url: str, path: str, *, timeout: int = 120,
                        retries: int = DEFAULT_RETRIES, backoff: float = DEFAULT_BACKOFF,
                        headers: dict = None) -> str:
    """带重试的流式下载。4xx 不重试（永久失败）；5xx / 瞬断重试。

    返回落盘后的本地路径；最终仍失败时抛出最后一次错误。
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    last = None
    for attempt in range(max(1, retries)):
        try:
            resp = requests.get(url, timeout=timeout, stream=True, headers=headers or {})
            if resp.status_code >= 500:
                resp.close()
                last = RuntimeError(f"Download server error {resp.status_code}: {url}")
            elif resp.status_code >= 400:
                resp.close()
                # 4xx 为永久失败，直接抛出，不重试
                raise RuntimeError(f"Download HTTP {resp.status_code}: {url}")
            else:
                with open(path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                return path
        except _RETRYABLE as e:
            last = e
        except RuntimeError:
            # 4xx 永久错误：直接上抛（5xx 的 RuntimeError 已被上面 'last' 捕获，不在此分支）
            raise
        if attempt < retries - 1 and last is not None:
            wait = backoff * (2 ** attempt)
            logger.warning("下载瞬断，%ss 后重试 (%d/%d): %s",
                           wait, attempt + 1, retries, last)
            time.sleep(wait)
            continue
        if last is not None:
            break
    raise last
