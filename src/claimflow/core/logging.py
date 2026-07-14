"""Structured logging configuration for production use."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from claimflow.core.config import Settings
from claimflow.core.context import get_correlation_id, get_request_id

# Field names that must never appear in cleartext logs.
_PII_KEYS: frozenset[str] = frozenset(
    {
        "cliente_nome",
        "customer_name",
        "full_name",
        "email",
        "e_mail",
        "cpf",
        "phone",
        "telefone",
        "mobile",
        "documento",
        "document_id",
        "raw_input",
        "raw_input_text",
        "reviewer_note",
        "analyst_notes",
    }
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_REDACTED = "[REDACTED]"


def redact_pii(value: object) -> object:
    """Recursively redact PII from log values (dicts, lists, strings)."""
    if isinstance(value, dict):
        return {
            key: (_REDACTED if key.lower() in _PII_KEYS else redact_pii(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_pii(item) for item in value]
    if isinstance(value, str):
        redacted = _EMAIL_RE.sub(_REDACTED, value)
        return _CPF_RE.sub(_REDACTED, redacted)
    return value


class ObservabilityFilter(logging.Filter):
    """Inject request/correlation IDs and redact PII on every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = get_request_id() or "-"
        if not getattr(record, "correlation_id", None):
            record.correlation_id = get_correlation_id() or "-"

        # Redact free-form message content (emails/CPF).
        if isinstance(record.msg, str):
            record.msg = redact_pii(record.msg)

        for key, value in list(record.__dict__.items()):
            if key in StructuredFormatter.RESERVED_ATTRS or key.startswith("_"):
                continue
            if key.lower() in _PII_KEYS:
                setattr(record, key, _REDACTED)
            else:
                setattr(record, key, redact_pii(value))

        return True


class StructuredFormatter(logging.Formatter):
    """JSON-like key=value formatter suitable for log aggregation pipelines."""

    RESERVED_ATTRS: frozenset[str] = frozenset(
        {
            *logging.makeLogRecord({}).__dict__.keys(),
            "message",
            "asctime",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        parts: list[str] = [
            f"timestamp={self.formatTime(record, self.datefmt)}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"request_id={getattr(record, 'request_id', '-')}",
            f"correlation_id={getattr(record, 'correlation_id', '-')}",
            f"message={record.getMessage()}",
        ]

        if record.exc_info:
            parts.append(f"exception={self.formatException(record.exc_info)}")

        for key, value in record.__dict__.items():
            if key in self.RESERVED_ATTRS or key.startswith("_"):
                continue
            if key in {"request_id", "correlation_id"}:
                continue
            parts.append(f"{key}={value}")

        return " ".join(parts)


def setup_logging(settings: Settings) -> None:
    """Configure the root logger with structured, PII-safe output.

    Args:
        settings: Application settings containing log level and environment.
    """
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
    handler.addFilter(ObservabilityFilter())
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)
    # Ensure filters also apply when libraries log via the root path.
    root_logger.addFilter(ObservabilityFilter())

    if settings.is_production:
        for noisy_logger in ("httpx", "httpcore", "urllib3", "dashscope"):
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter:
    """Return a logger adapter that injects static context into every log record.

    Args:
        name: Logger name, typically ``__name__``.
        **context: Key-value pairs attached to every log entry from this logger.
    """
    return logging.LoggerAdapter(logging.getLogger(name), extra=context)
