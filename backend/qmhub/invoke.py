"""qmhub - Invoke API (能力调用与任务查询)"""


class InvokeAPI:
    def __init__(self, client):
        self._client = client

    def create(
        self,
        slug: str,
        input_url: str = None,
        input_base64: str = None,
        params: dict = None,
        duration_seconds: float = None,
    ) -> dict:
        """
        调用一个能力。

        Args:
            slug: 能力唯一标识，如 "video-watermark-removal"
            input_url: 输入来源 URL（与 input_base64 二选一）
            input_base64: 输入来源 Base64（与 input_url 二选一）
            params: 附加参数（如视频水印的 x1/y1/x2/y2/mode）
            duration_seconds: 视频时长（秒）。视频类能力会在提交上游前用该时长
                预估费用并与用户积分比对；积分不足时接口返回
                status="insufficient_points"（HTTP 402，提示「积分不足以本次任务消耗，请充值积分」）。
        Returns:
            同步能力返回 {status:"success", result_url, points_charged, ...}
            异步能力返回 {status:"processing", task_id, request_id, ...}
        """
        payload = {
            "slug": slug,
            "input_url": input_url,
            "input_base64": input_base64,
            "params": params or {},
            "duration_seconds": duration_seconds,
        }
        return self._client._request("POST", "/api/capability/invoke", json=payload)

    def task_status(self, request_id: int) -> dict:
        """查询异步任务状态（单次，不轮询）。"""
        return self._client._request("GET", f"/api/capability/tasks/{request_id}")
