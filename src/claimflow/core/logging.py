"""Structured logging configuration for production use."""

import logging
import sys
from typing import Any

from claimflow.core.config import Settings


class StructuredFormatter(logging.Formatter):
    """JSON-like key=value formatter suitable for log aggregation pipelines."""

    RESERVED_ATTRS: frozenset[str] = frozenset(logging.makeLogRecord({}).__dict__.keys())

    def format(self, record: logging.LogRecord) -> str:
        parts: list[str] = [
            f"timestamp={self.formatTime(record, self.datefmt)}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"message={record.getMessage()}",
        ]

        if record.exc_info:
            parts.append(f"exception={self.formatException(record.exc_info)}")

        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith("_"):
                parts.append(f"{key}={value}")

        return " ".join(parts)


def setup_logging(settings: Settings) -> None:
    """Configure the root logger with structured output.

    Args:
      settings: Application settings containing log level and environment.
    """
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # Reduce noise from third-party libraries in production
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
