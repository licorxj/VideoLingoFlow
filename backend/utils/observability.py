import json
import logging
import time
import uuid
from contextvars import ContextVar


correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def get_correlation_id(value: str | None = None) -> str:
    return value or correlation_id.get() or uuid.uuid4().hex


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)), "level": record.levelname, "logger": record.name, "message": record.getMessage(), "correlation_id": getattr(record, "correlation_id", correlation_id.get())}, ensure_ascii=False)
