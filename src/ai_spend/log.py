"""Structured logging configuration for ai-spend."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format log records as compact single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra_fields"):
            data["fields"] = record.extra_fields
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(verbose: bool = False) -> None:
    """Configure structured JSON logging for ai-spend."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("ai_spend")
    logger.setLevel(level)
    # Avoid duplicate handlers if configure_logging is called multiple times.
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the ai_spend namespace."""
    return logging.getLogger(f"ai_spend.{name}")
