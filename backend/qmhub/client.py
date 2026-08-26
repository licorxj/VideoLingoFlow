"""qmhub - Main client for Capability Hub (能力Hub) SDK

后端真实接口前缀为 /api/capability/*，使用 Bearer API Key 认证。
响应统一封装为 {"code": 0, "msg": "...", "data": {...}}，本客户端自动解包 data。
"""

import time

import json

import requests

# 生产环境域名（前端 nginx 将 /api 转发到后端，无需暴露端口）
DEFAULT_BASE_URL = "https://www.licorxj.online"

try:
    from .exceptions import (
        AuthenticationError,
        InsufficientPointsError,
        NotFoundError,
        QmHubError,
        RateLimitError,
        ServerError,
    )
except ImportError:
    from qmhub.exceptions import (
        AuthenticationError,
        InsufficientPointsError,
        NotFoundError,
        QmHubError,
        RateLimitError,
        ServerError,
    )


class QmHubClient:
    def __init__(
        self,
        api_key: str = None,
        username: str = None,
        password: str = None,
        base_url: str = None,
        timeout: int = 30,
    ):
        """
        初始化能力 Hub 客户端。

        Args:
            api_key: 能力 Hub 的 API Key（Bearer 认证，优先）
            username/password: 用户名密码（Basic 认证，备用）
            base_url: 服务地址，默认 https://www.licorxj.online （前端转发 /api，无需端口）
            timeout: 单次请求超时（秒）
        """
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key
        self.username = username
        self.password = password
        self.timeout = timeout
        self._session = requests.Session()

        # 子模块
        try:
            from .capabilities import CapabilitiesAPI
            from .invoke import InvokeAPI
            from .video_watermark import VideoWatermarkAPI
            from .mail_forwarding import MailForwardingAPI
        except ImportError:
            from qmhub.capabilities import CapabilitiesAPI
            from qmhub.invoke import InvokeAPI
            from qmhub.video_watermark import VideoWatermarkAPI
            from qmhub.mail_forwarding import MailForwardingAPI

        self.capabilities = CapabilitiesAPI(self)
        self.invoke = InvokeAPI(self)
        self.video_watermark = VideoWatermarkAPI(self)
        self.mail_forwarding = MailForwardingAPI(self)

    # ────────────────────────────────────────────
    # 内部：认证与请求
    # ────────────────────────────────────────────
    def _get_headers(self) -> dict:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        elif self.username and self.password:
            # 后端通过自定义请求头 X-Capability-Username / X-Capability-Password 鉴权
            return {
                "X-Capability-Username": self.username,
                "X-Capability-Password": self.password,
            }
        # 未提供凭据：允许匿名访问公开接口（如能力列表），需认证接口由后端返回 401
        return {}

    def _request(self, method: str, path: str, **kwargs):
        """
        发起请求并解包后端统一响应 {"code","msg","data"}。
        返回：data 字段（成功时）。
        失败：根据 HTTP 状态码或业务 code 抛出对应异常。
        """
        url = f"{self.base_url}{path}"
        headers = self._get_headers()
        headers.update(kwargs.pop("headers", {}))
        kwargs.setdefault("timeout", self.timeout)

        response = self._session.request(method, url, headers=headers, **kwargs)

        # HTTP 层错误
        if response.status_code == 401:
            raise AuthenticationError("认证失败，请检查 API Key")
        elif response.status_code == 402:
            raise InsufficientPointsError("积分不足")
        elif response.status_code == 404:
            raise NotFoundError("资源不存在")
        elif response.status_code == 429:
            raise RateLimitError("请求频率超限")
        elif response.status_code >= 500:
            detail = ""
            try:
                _b = response.json()
                detail = (_b.get("detail") or _b.get("msg") or json.dumps(_b, ensure_ascii=False))[:800]
            except Exception:
                detail = (response.text or "")[:800]
            raise ServerError(f"服务器错误: {response.status_code} | {detail}")

        # 解析后端统一封装
        try:
            body = response.json()
        except ValueError:
            if response.status_code != 200:
                raise QmHubError(f"HTTP {response.status_code}", status_code=response.status_code)
            raise QmHubError("响应不是合法 JSON", response_data=response.text)

        # 兼容两种响应结构：
        #   1) 标准封装 {"code":0,"msg":"","data":...}（如公开能力列表）
        #   2) 能力调用/任务等自定义结构（无 code 字段，直接返回 JSON 本体）
        if "code" in body:
            code = body.get("code", 0)
            if code != 0:
                msg = body.get("msg") or body.get("detail") or f"业务错误 code={code}"
                if code in (401, 402, 404, 429):
                    exc_map = {
                        401: AuthenticationError,
                        402: InsufficientPointsError,
                        404: NotFoundError,
                        429: RateLimitError,
                    }
                    raise exc_map[code](msg)
                raise QmHubError(msg, status_code=code, response_data=body)
            return body.get("data")

        # 无 code 字段：直接返回整个响应体（能力调用/任务状态等）
        return body

    # ────────────────────────────────────────────
    # 对外：任务轮询（视频水印等异步能力复用）
    # ────────────────────────────────────────────
    def wait_for_task(
        self,
        request_id: int,
        poll_interval: float = 30.0,
        timeout: float = 1800.0,
    ) -> dict:
        """
        轮询异步任务直到终态（success/failed）。

        Args:
            request_id: 调用 /invoke 返回的 request_id
            poll_interval: 轮询间隔（秒，建议 30~60）
            timeout: 总超时（秒）
        Returns:
            dict: 终态的任务结果（含 status/result_url/duration_seconds/fee 等）
        """
        deadline = time.time() + timeout
        last = None
        while True:
            last = self._request("GET", f"/api/capability/tasks/{request_id}")
            if last.get("status") != "processing":
                return last
            if time.time() >= deadline:
                raise QmHubError("任务轮询超时", response_data=last)
            time.sleep(poll_interval)
