"""Tests for structured logging."""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from io import StringIO

import pytest

from ai_spend.log import JsonFormatter, configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_logging() -> Generator[None, None, None]:
    """Clean up ai_spend logger state after each test."""
    yield
    logger = logging.getLogger("ai_spend")
    logger.handlers.clear()
    logger.propagate = True
    logger.setLevel(logging.NOTSET)


class TestJsonFormatter:
    def test_outputs_valid_json(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["msg"] == "hello"
        assert data["level"] == "info"

    def test_includes_extra_fields(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="sync",
            args=(),
            exc_info=None,
        )
        record.extra_fields = {"provider": "openai", "records": 5}
        output = formatter.format(record)
        data = json.loads(output)
        assert data["fields"]["provider"] == "openai"
        assert data["fields"]["records"] == 5

    def test_includes_exception(self) -> None:
        import sys

        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except Exception:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="fail",
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exc" in data
        assert "boom" in data["exc"]


class TestConfigureLogging:
    def test_sets_level_info_by_default(self) -> None:
        configure_logging(verbose=False)
        logger = logging.getLogger("ai_spend")
        assert logger.level == logging.INFO

    def test_verbose_sets_debug(self) -> None:
        configure_logging(verbose=True)
        logger = logging.getLogger("ai_spend")
        assert logger.level == logging.DEBUG

    def test_clears_existing_handlers(self) -> None:
        configure_logging(verbose=False)
        configure_logging(verbose=False)
        logger = logging.getLogger("ai_spend")
        assert len(logger.handlers) == 1

    def test_outputs_json_to_handler(self) -> None:
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("ai_spend.test_output")
        logger.handlers.clear()
        logger.propagate = False
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("test_event", extra={"extra_fields": {"key": "val"}})
        handler.flush()
        output = stream.getvalue().strip()
        data = json.loads(output)
        assert data["msg"] == "test_event"
        assert data["fields"]["key"] == "val"

        logger.handlers.clear()


class TestGetLogger:
    def test_returns_ai_spend_namespaced_logger(self) -> None:
        logger = get_logger("foo")
        assert logger.name == "ai_spend.foo"
