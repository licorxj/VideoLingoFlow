"""s_http_request: Configurable HTTP request workflow step."""
import ipaddress
import json
import os
import re
import socket
import time
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
import requests

from backend.steps.base_step import BaseStep


def _resolve_value(value: Any, task_dir: str) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    value = str(value)
    path = value if os.path.isabs(value) else os.path.join(task_dir, value)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig") as file:
            return file.read()
    return value


def _replace_placeholders(template: str, values: dict[str, str]) -> str:
    return re.sub(r"\{(input_[123]|request_data)\}", lambda match: values[match.group(1)], template)


def _parse_headers(value: str) -> dict[str, str]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("请求头必须是 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise ValueError("请求头必须是 JSON 对象")
    return {str(key): str(item) for key, item in parsed.items()}


def _is_success_status(status_code: int, expected: str) -> bool:
    for item in expected.replace(" ", "").split(","):
        if not item:
            continue
        if item.endswith("xx") and len(item) == 3 and item[0].isdigit():
            if status_code // 100 == int(item[0]):
                return True
        elif "-" in item:
            try:
                start, end = (int(part) for part in item.split("-", 1))
                if start <= status_code <= end:
                    return True
            except ValueError:
                continue
        else:
            try:
                if status_code == int(item):
                    return True
            except ValueError:
                continue
    return False


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("请求 URL 必须是有效的 HTTP 或 HTTPS 地址")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"无法解析请求地址: {parsed.hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("不允许请求本地、私有或保留网络地址")


class S_HttpRequest(BaseStep):
    step_id = "s_http_request"
    step_name = "网络请求"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        return any(
            os.path.exists(os.path.join(task_dir, "output", f"http_{node_id}.{extension}"))
            for extension in ("json", "txt")
        )

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}
        ignore_inputs = bool(config.get("ignore_connected_inputs", False))
        values = {
            "input_1": "" if ignore_inputs else _resolve_value(inputs.get("input_1", ""), task_dir),
            "input_2": "" if ignore_inputs else _resolve_value(inputs.get("input_2", ""), task_dir),
            "input_3": "" if ignore_inputs else _resolve_value(inputs.get("input_3", ""), task_dir),
            "request_data": "" if ignore_inputs else _resolve_value(inputs.get("request_data", ""), task_dir),
        }
        method = str(config.get("method", "GET")).upper()
        url = _replace_placeholders(str(config.get("url", "")).strip(), values)
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ValueError("不支持的请求方法")
        _validate_url(url)
        headers = _parse_headers(_replace_placeholders(str(config.get("headers", "")), values))
        body = _replace_placeholders(str(config.get("body", "")), values)
        body_type = str(config.get("body_type", "json"))
        timeout = max(1.0, float(config.get("timeout", 30)))
        expected_status = str(config.get("success_status_codes", "200-299"))
        retry_count = max(0, int(config.get("retry_count", 0))) if config.get("retry_enabled") else 0
        retry_interval = max(0.0, float(config.get("retry_interval", 1)))
        client_type = str(config.get("request_client", "requests"))
        browser = str(config.get("browser_impersonation", "none"))

        if browser != "none" and client_type != "curl":
            headers.setdefault("User-Agent", {
                "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
                "edge": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36 Edg/131.0",
                "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
                "safari": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.1 Safari/605.1.15",
            }.get(browser, ""))

        request_kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
        if body:
            if body_type == "json":
                try:
                    request_kwargs["json"] = json.loads(body)
                except json.JSONDecodeError as exc:
                    raise ValueError("JSON 请求体格式无效") from exc
            else:
                request_kwargs["content"] = body.encode("utf-8")
                headers.setdefault("Content-Type", "text/plain; charset=utf-8")

        response = None
        for attempt in range(retry_count + 1):
            if callback:
                callback(10 + int(60 * attempt / max(1, retry_count + 1)), f"正在执行请求（第 {attempt + 1} 次）")
            try:
                if client_type == "httpx":
                    response = httpx.request(method, url, follow_redirects=False, trust_env=False, **request_kwargs)
                elif client_type == "curl":
                    try:
                        from curl_cffi import requests as curl_requests
                    except ImportError as exc:
                        raise RuntimeError("curl 请求需要安装 curl_cffi") from exc
                    curl_kwargs = dict(request_kwargs)
                    if browser != "none":
                        curl_kwargs["impersonate"] = browser
                    response = curl_requests.request(method, url, allow_redirects=False, **curl_kwargs)
                else:
                    response = requests.request(method, url, allow_redirects=False, **request_kwargs)
                if _is_success_status(response.status_code, expected_status):
                    break
                raise RuntimeError(f"请求返回状态码 {response.status_code}，未命中成功状态码设置 {expected_status}")
            except Exception as exc:
                if attempt >= retry_count:
                    raise RuntimeError(f"网络请求失败: {exc}") from exc
                if callback:
                    callback(20 + int(60 * attempt / max(1, retry_count + 1)), f"请求失败，{retry_interval:g} 秒后重试")
                time.sleep(retry_interval)

        if response is None:
            raise RuntimeError("网络请求未返回响应")
        if callback:
            callback(75, "正在保存响应")
        output_format = str(config.get("output_format", "auto"))
        content_type = response.headers.get("content-type", "").lower()
        is_json = output_format == "json" or (output_format == "auto" and "json" in content_type)
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        status_output = str(response.status_code)
        if is_json:
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError("响应不是有效 JSON，无法按 JSON 格式保存") from exc
            relative_path = f"output/http_{node_id}.json"
            with open(os.path.join(task_dir, relative_path), "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            outputs = {"result": relative_path, "json": relative_path, "text": json.dumps(data, ensure_ascii=False), "status": status_output}
        else:
            text = response.text
            relative_path = f"output/http_{node_id}.txt"
            with open(os.path.join(task_dir, relative_path), "w", encoding="utf-8") as file:
                file.write(text)
            outputs = {"result": relative_path, "json": "", "text": text, "status": status_output}
        if callback:
            callback(100, f"响应已保存为 {os.path.basename(relative_path)}")
        return {"artifacts": [relative_path], "outputs": outputs}
