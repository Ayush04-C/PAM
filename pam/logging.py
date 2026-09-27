"""Structured logging with request-context support and secret redaction."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

REDACTED = "[REDACTED]"
SECRET_FIELD_NAMES = frozenset(
    {"api_key", "apikey", "authorization", "credential", "password", "secret", "token"}
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)\b"
    r"\s*([=:])\s*([^,\s]+)"
)
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


def redact(value: Any, field_name: str | None = None) -> Any:
    """Return a logging-safe version of a value without known secrets."""
    if field_name is not None and field_name.lower() in SECRET_FIELD_NAMES:
        return REDACTED
    if isinstance(value, Mapping):
        return {key: redact(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return _SECRET_ASSIGNMENT.sub(r"\1\2 " + REDACTED, value)
    return value


class JsonFormatter(logging.Formatter):
    """Emit small, machine-readable log records."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        request_id = request_id_context.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_"):
                payload[key] = redact(value, key)
        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging() -> None:
    """Configure PAM's application logger without modifying the root logger."""
    logger = logging.getLogger("pam")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if any(isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
