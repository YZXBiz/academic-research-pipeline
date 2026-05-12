"""Logging configuration for the academic pipeline.

Two handlers: console (StreamHandler) + rotating file (RotatingFileHandler).
File logging is config-driven via PipelineConfig (log_dir, log_max_bytes,
log_backup_count). Pass log_dir=None to disable file logging (e.g. in tests).
"""

from __future__ import annotations

import json as _json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


_NOISY_LOGGERS = ("httpx", "httpcore")

_PLAIN_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_CONSOLE_DATEFMT = "%H:%M:%S"
_FILE_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _JSONFormatter(logging.Formatter):
    """Structured JSON log lines for production aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON line."""
        return _json.dumps(
            {
                "ts": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
            }
        )


def configure_logging(
    verbose: bool = False,
    json_logs: bool = False,
    log_dir: str | None = "logs",
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
) -> None:
    """Set up console + optional rotating file logging.

    Args:
        verbose: If True, set root log level to DEBUG; otherwise INFO.
        json_logs: If True, use structured JSON log lines on console.
        log_dir: Directory for log files. None disables file logging.
        max_bytes: Max size per log file before rotation (default 10 MB).
        backup_count: Number of rotated backup files to keep (default 5).
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Console handler
    console = logging.StreamHandler()
    if json_logs:
        console.setFormatter(_JSONFormatter())
    else:
        console.setFormatter(logging.Formatter(_PLAIN_FMT, datefmt=_CONSOLE_DATEFMT))
    logging.root.addHandler(console)
    logging.root.setLevel(level)

    # Rotating file handler
    if log_dir is not None:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path / "pipeline.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_PLAIN_FMT, datefmt=_FILE_DATEFMT))
        file_handler.setLevel(logging.DEBUG)
        logging.root.addHandler(file_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
