"""qmhub - 视频水印擦除高层封装
提交任务 -> 轮询 -> 返回结果。
不成功不扣费；成功按视频时长计费。
示例：
    from qmhub import QmHubClient

    client = QmHubClient(api_key="cbk_xxx")  # 默认 base_url=https://www.licorxj.online

    result = client.video_watermark.remove(
        video_url="https://example.com/video.mp4",
        mode="protect",
        poll=True,            # 是否阻塞轮询直到完成
        poll_interval=30,     # 轮询间隔（秒）
        timeout=1800,         # 总超时（秒）
    )
    print(result["result_url"], result.get("duration_seconds"), result.get("fee"))
"""

VIDEO_WATERMARK_SLUG = "video-watermark-removal"


class VideoWatermarkAPI:
    def __init__(self, client):
        self._client = client

    def submit(
        self,
        video_url: str = None,
        video_base64: str = None,
        x1: int = 0,
        y1: int = 0,
        x2: int = 0,
        y2: int = 0,
        mode: str = "normal",
        duration_seconds: float = None,
    ) -> dict:
        """
        提交视频水印擦除任务（仅提交，不等待）。

        坐标与模式参数位置：放在请求体 params 内，由后端转发到上游任务体。
            params = { "x1":.., "y1":.., "x2":.., "y2":.., "mode": "normal"|"protect" }

        Returns:
            {status:"processing", task_id, request_id, message}
        """
        if not video_url :
            raise ValueError("必须提供 video_url")

        params = {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "mode": mode,
        }
        return self._client.invoke.create(
            slug=VIDEO_WATERMARK_SLUG,
            input_url=video_url,
            input_base64=video_base64,
            params=params,
            duration_seconds=duration_seconds,
        )

    def remove(
        self,
        video_url: str = None,
        video_base64: str = None,
        x1: int = 0,
        y1: int = 0,
        x2: int = 0,
        y2: int = 0,
        mode: str = "normal",
        duration_seconds: float = None,
        poll: bool = True,
        poll_interval: float = 30.0,
        timeout: float = 1800.0,
    ) -> dict:
        """
        提交并（可选）等待视频水印擦除完成，返回最终结果。

        Args:
            video_url 
            x1,y1,x2,y2: 水印范围坐标（可选，默认 0）
            mode: "normal"（默认）或 "protect"（保护模式）
            duration_seconds: 视频时长（秒），用于预扣费积分校验
            poll: 是否阻塞轮询直到终态（默认 True）
            poll_interval: 轮询间隔（秒）
            timeout: 总超时（秒）
        Returns:
            dict: {status, result_url, duration_seconds, billing_seconds, fee, points_charged, ...}
        """
        submitted = self.submit(
            video_url=video_url,
            video_base64=video_base64,
            x1=x1, y1=y1, x2=x2, y2=y2,
            mode=mode,
            duration_seconds=duration_seconds,
        )
        if not poll:
            return submitted

        request_id = submitted.get("request_id")
        if not request_id:
            raise RuntimeError(f"提交后未返回 request_id: {submitted}")

        return self._client.wait_for_task(
            request_id,
            poll_interval=poll_interval,
            timeout=timeout,
        )

    def status(self, request_id: int) -> dict:
        """查询视频水印任务状态（单次）。"""
        return self._client.invoke.task_status(request_id)
