"""qmhub - Python SDK for Capability Hub (能力Hub)"""

try:
    # 项目内作为 backend.qmhub 使用时
    from .client import QmHubClient
    from .exceptions import (
        AuthenticationError,
        InsufficientPointsError,
        NotFoundError,
        QmHubError,
        RateLimitError,
        ServerError,
    )
    from .video_watermark import VIDEO_WATERMARK_SLUG
    from .mail_forwarding import MailForwardingAPI
except ImportError:
    # 作为顶层 qmhub 包安装使用时（pip install .）
    from qmhub.client import QmHubClient
    from qmhub.exceptions import (
        AuthenticationError,
        InsufficientPointsError,
        NotFoundError,
        QmHubError,
        RateLimitError,
        ServerError,
    )
    from qmhub.video_watermark import VIDEO_WATERMARK_SLUG
    from qmhub.mail_forwarding import MailForwardingAPI

__version__ = "0.3.0"
__all__ = [
    "QmHubClient",
    "QmHubError",
    "AuthenticationError",
    "InsufficientPointsError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "VIDEO_WATERMARK_SLUG",
    "MailForwardingAPI",
]
