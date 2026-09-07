#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exceptions raised by the kie.ai SDK."""


class KieError(Exception):
    """Base class for all SDK errors."""


class KieRequestError(KieError):
    """Raised when the API returns a non-2xx HTTP status or ``code != 200``."""

    def __init__(self, message: str, *, status: int = 0, body: object = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body


class KieModelNotFound(KieError):
    """Raised when a model key cannot be resolved in the catalog."""


class KieTaskFailed(KieError):
    """Raised when an async task ends in a failed state."""

    def __init__(self, message: str, *, task_id: str = "", body: object = None):
        super().__init__(message)
        self.message = message
        self.task_id = task_id
        self.body = body


class KieTimeout(KieError):
    """Raised when a task does not finish within ``max_poll`` attempts."""

    def __init__(self, message: str, *, task_id: str = ""):
        super().__init__(message)
        self.message = message
        self.task_id = task_id
