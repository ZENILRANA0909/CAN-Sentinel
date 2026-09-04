"""Structured logging for CAN-Sentinel.

Two formatters are available:

* a human readable console formatter used during development, and
* a line-delimited JSON formatter (``LOG_JSON=true``) suited to log shippers.

Extra structured fields are attached to a record via ``logger.info(..., extra={"context": {...}})``.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

_CONFIGURED = False

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


def _record_context(record: logging.LogRecord) -> dict[str, Any]:
    context = dict(getattr(record, "context", {}) or {})
    for key, value in record.__dict__.items():
        if key not in _RESERVED and key != "context":
            context[key] = value
    return context


class JsonFormatter(logging.Formatter):
    """Serialise log records as single-line JSON documents."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = _record_context(record)
        if context:
            payload["context"] = context
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Compact, aligned console output with an inline context suffix."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        context = _record_context(record)
        if context:
            rendered = " ".join(f"{key}={value!r}" for key, value in sorted(context.items()))
            base = f"{base} :: {rendered}"
        return base


def configure_logging(
    *,
    level: str = "INFO",
    log_dir: Path | None = None,
    log_file: str = "can-sentinel.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    json_output: bool = False,
    to_file: bool = True,
    force: bool = False,
) -> None:
    """Install console (and optionally rotating file) handlers on the root logger."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(level)
    formatter: logging.Formatter = JsonFormatter() if json_output else ConsoleFormatter()

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    if to_file and log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_dir / log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(JsonFormatter() if json_output else formatter)
            root.addHandler(file_handler)
        except OSError as exc:  # pragma: no cover - depends on the filesystem
            root.warning("File logging disabled: %s", exc)

    # Uvicorn ships its own handlers; route everything through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    logging.getLogger("can").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced application logger."""
    qualified = name if name.startswith("can_sentinel") else f"can_sentinel.{name}"
    return logging.getLogger(qualified)
