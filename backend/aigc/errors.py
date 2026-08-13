"""AIGC 能力模块的异常类型。"""


class AIGCError(Exception):
    """AIGC 能力调用失败的统一异常。"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
