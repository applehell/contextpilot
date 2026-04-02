"""Tests for src.core.log — centralized logging setup."""
import json
import logging
import os

import pytest

from src.core.log import JSONFormatter, get_logger, setup_logging


@pytest.fixture(autouse=True)
def _clean_root_logger():
    """Remove handlers added by setup_logging between tests."""
    root = logging.getLogger("contextpilot")
    original_handlers = list(root.handlers)
    original_level = root.level
    yield
    root.handlers = original_handlers
    root.level = original_level


class TestGetLogger:
    def test_returns_named_logger(self):
        lg = get_logger("foo.bar")
        assert lg.name == "contextpilot.foo.bar"

    def test_returns_logger_instance(self):
        lg = get_logger("test")
        assert isinstance(lg, logging.Logger)


class TestSetupLogging:
    def test_creates_handler(self):
        root = logging.getLogger("contextpilot")
        root.handlers.clear()
        setup_logging()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)

    def test_does_not_duplicate_handlers(self):
        root = logging.getLogger("contextpilot")
        root.handlers.clear()
        setup_logging()
        setup_logging()
        assert len(root.handlers) == 1

    def test_default_level_is_info(self):
        root = logging.getLogger("contextpilot")
        root.handlers.clear()
        os.environ.pop("CONTEXTPILOT_LOG_LEVEL", None)
        setup_logging()
        assert root.level == logging.INFO

    def test_level_from_env(self, monkeypatch):
        root = logging.getLogger("contextpilot")
        root.handlers.clear()
        monkeypatch.setenv("CONTEXTPILOT_LOG_LEVEL", "DEBUG")
        setup_logging()
        assert root.level == logging.DEBUG

    def test_json_format_from_env(self, monkeypatch):
        root = logging.getLogger("contextpilot")
        root.handlers.clear()
        monkeypatch.setenv("CONTEXTPILOT_LOG_FORMAT", "json")
        setup_logging()
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_text_format_default(self):
        root = logging.getLogger("contextpilot")
        root.handlers.clear()
        os.environ.pop("CONTEXTPILOT_LOG_FORMAT", None)
        setup_logging()
        assert not isinstance(root.handlers[0].formatter, JSONFormatter)


class TestJSONFormatter:
    def test_produces_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="contextpilot.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "contextpilot.test"
        assert data["message"] == "hello world"
        assert "timestamp" in data

    def test_includes_extra_data(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="contextpilot.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.extra_data = {"version": "1.0", "port": 8080}
        output = formatter.format(record)
        data = json.loads(output)
        assert data["version"] == "1.0"
        assert data["port"] == 8080

    def test_includes_exception(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="contextpilot.test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]
