"""Tests for logging_config.configure_logging and _JSONFormatter."""

from __future__ import annotations

import logging

from academic_pipeline.logging_config import _JSONFormatter, configure_logging


class TestConfigureLogging:
    def setup_method(self):
        """Reset root logger before each test to avoid cross-test pollution."""
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.WARNING)
        root.manager.loggerClass = None

    def test_verbose_sets_debug_level(self):
        configure_logging(verbose=True, json_logs=True, log_dir=None)
        assert logging.getLogger().level == logging.DEBUG

    def test_non_verbose_sets_info_level(self):
        configure_logging(verbose=False, json_logs=True, log_dir=None)
        assert logging.getLogger().level == logging.INFO

    def test_noisy_loggers_suppressed(self):
        configure_logging(verbose=True, json_logs=True, log_dir=None)
        for name in ("httpx", "httpcore"):
            assert logging.getLogger(name).level == logging.WARNING

    def test_json_logs_adds_json_formatter(self):
        configure_logging(verbose=False, json_logs=True, log_dir=None)
        root = logging.getLogger()
        json_handlers = [h for h in root.handlers if isinstance(h.formatter, _JSONFormatter)]
        assert len(json_handlers) >= 1

    def test_json_logs_verbose_sets_debug(self):
        configure_logging(verbose=True, json_logs=True, log_dir=None)
        assert logging.getLogger().level == logging.DEBUG

    def test_plain_text_no_file_has_console_only(self):
        """Log_dir=None should skip file handler."""
        configure_logging(verbose=False, json_logs=False, log_dir=None)
        root = logging.getLogger()
        assert root.level == logging.INFO
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in handler_types
        assert "RotatingFileHandler" not in handler_types

    def test_plain_text_with_file_has_both_handlers(self, tmp_path):
        """Log_dir set should add both console and rotating file handler."""
        configure_logging(verbose=False, json_logs=False, log_dir=str(tmp_path))
        root = logging.getLogger()
        handler_types = [type(h).__name__ for h in root.handlers]
        assert "StreamHandler" in handler_types
        assert "RotatingFileHandler" in handler_types
        assert (tmp_path / "pipeline.log").exists()

    def test_plain_text_verbose_sets_debug(self):
        configure_logging(verbose=True, json_logs=False, log_dir=None)
        assert logging.getLogger().level == logging.DEBUG


class TestJSONFormatter:
    def test_format_produces_valid_json(self):
        import json

        formatter = _JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["msg"] == "Hello world"
        assert "ts" in parsed
        assert "exc" not in parsed

    def test_format_includes_exception_info(self):
        import json
        import sys

        formatter = _JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Something failed",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exc" in parsed
        assert "ValueError" in parsed["exc"]
        assert "test error" in parsed["exc"]
