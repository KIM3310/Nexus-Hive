"""
Structured logging configuration for Nexus-Hive.

Provides a centralized logging setup with JSON formatting, request ID propagation,
and configurable log levels for production observability.
"""

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Optional


# Thread-local storage for request context propagation
_request_context = threading.local()


def set_request_id(request_id: str) -> None:
    """Set the current request ID for log correlation.

    Args:
        request_id: Unique identifier for the current request.
    """
    _request_context.request_id = request_id


def get_request_id() -> Optional[str]:
    """Retrieve the current request ID from thread-local storage.

    Returns:
        The current request ID, or None if not set.
    """
    return getattr(_request_context, "request_id", None)


def clear_request_id() -> None:
    """Clear the current request ID from thread-local storage."""
    _request_context.request_id = None


class StructuredJsonFormatter(logging.Formatter):
    """JSON log formatter that emits structured log lines with request context.

    Each log line includes timestamp, level, logger name, message, and any
    extra fields passed via the ``extra`` keyword argument to logging calls.
    When a request ID is set via :func:`set_request_id`, it is automatically
    attached to every log record.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a single-line JSON object.

        Args:
            record: The log record to format.

        Returns:
            A JSON string representing the structured log entry.
        """
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "nexus-hive",
        }

        request_id = get_request_id()
        if request_id:
            log_entry["request_id"] = request_id

        # Merge any extra fields passed through logging calls
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_entry.update(record.extra_fields)

        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=True, default=str)


def configure_logging(level: Optional[str] = None) -> logging.Logger:
    """Configure and return the root nexus-hive logger.

    Sets up JSON-structured logging to stderr with the specified level.
    Safe to call multiple times; handlers are only added once.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR). Defaults to the
            ``NEXUS_HIVE_LOG_LEVEL`` environment variable, falling back to INFO.

    Returns:
        The configured ``nexus_hive`` logger instance.
    """
    resolved_level = level or os.getenv("NEXUS_HIVE_LOG_LEVEL", "INFO").strip().upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    logger = logging.getLogger("nexus_hive")

    # Prevent duplicate handlers on repeated calls
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)

    logger.setLevel(numeric_level)
    return logger


# Module-level logger for convenience imports
logger = configure_logging()
