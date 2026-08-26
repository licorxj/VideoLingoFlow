"""qmhub - Custom exceptions for Capability Hub SDK"""


class QmHubError(Exception):
    """Base exception for QmHub SDK errors."""

    def __init__(self, message: str, status_code: int = None, response_data: dict = None):
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(self.message)


class AuthenticationError(QmHubError):
    """Raised when authentication fails (401)."""

    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, status_code=401, **kwargs)


class InsufficientPointsError(QmHubError):
    """Raised when points are insufficient (402)."""

    def __init__(self, message: str = "Insufficient points", **kwargs):
        super().__init__(message, status_code=402, **kwargs)


class NotFoundError(QmHubError):
    """Raised when a resource is not found (404)."""

    def __init__(self, message: str = "Resource not found", **kwargs):
        super().__init__(message, status_code=404, **kwargs)


class RateLimitError(QmHubError):
    """Raised when rate limit is exceeded (429)."""

    def __init__(self, message: str = "Rate limit exceeded", **kwargs):
        super().__init__(message, status_code=429, **kwargs)


class ServerError(QmHubError):
    """Raised when server returns 5xx error."""

    def __init__(self, message: str = "Server error", **kwargs):
        super().__init__(message, **kwargs)
