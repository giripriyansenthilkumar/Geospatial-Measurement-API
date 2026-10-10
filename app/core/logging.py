"""Structured logging configuration with request correlation ID tracking."""

import contextvars
import logging
import sys
import uuid
from typing import Optional

# Context variable to propagate request_id across async contexts
request_id_ctx_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)


def get_request_id() -> str:
    """Return the current request ID or generate a fallback."""
    rid = request_id_ctx_var.get()
    return rid or "system"


def set_request_id(rid: Optional[str] = None) -> str:
    """Set or generate a new request ID in the context."""
    new_id = rid or str(uuid.uuid4())
    request_id_ctx_var.set(new_id)
    return new_id


class RequestIdFilter(logging.Filter):
    """Logging filter that injects the current request_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [req_id=%(request_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silence overly verbose external loggers if needed
    logging.getLogger("pyogrio").setLevel(logging.WARNING)
    logging.getLogger("fiona").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


logger = logging.getLogger("geo_measure")
