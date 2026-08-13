"""Logging utilities."""
import logging
import os
import sys
from backend.utils.observability import CorrelationFilter, JsonFormatter

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")


def get_logger(name: str) -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        # File handler
        fh = logging.FileHandler(os.path.join(LOG_DIR, f"{name}.log"), encoding="utf-8")
        fh.addFilter(CorrelationFilter())
        fh.setFormatter(JsonFormatter())
        logger.addHandler(fh)
        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.addFilter(CorrelationFilter())
        ch.setFormatter(JsonFormatter())
        logger.addHandler(ch)
    return logger
