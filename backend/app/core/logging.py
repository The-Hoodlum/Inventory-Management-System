"""Minimal structured logging.

A tiny wrapper that emits JSON log lines without extra dependencies. Swap for
structlog/loguru later if desired; the ``get_logger(...).info(event, **kw)``
call-site API is intentionally structlog-like so that migration is trivial.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Attach structured extras placed on the record by _BoundLogger.
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", as_json: bool = True) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if as_json else logging.Formatter(
        "%(levelname)s %(name)s %(message)s"
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    _CONFIGURED = True


class _BoundLogger:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, lvl: int, event: str, **fields: Any) -> None:
        self._logger.log(lvl, event, extra={"extra_fields": fields})

    def debug(self, event: str, **f: Any) -> None:
        self._log(logging.DEBUG, event, **f)

    def info(self, event: str, **f: Any) -> None:
        self._log(logging.INFO, event, **f)

    def warning(self, event: str, **f: Any) -> None:
        self._log(logging.WARNING, event, **f)

    def error(self, event: str, **f: Any) -> None:
        self._log(logging.ERROR, event, **f)

    def exception(self, event: str, **f: Any) -> None:
        self._logger.exception(event, extra={"extra_fields": f})


def get_logger(name: str) -> _BoundLogger:
    return _BoundLogger(logging.getLogger(name))
