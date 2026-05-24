"""
Logging configuration — switchable between human-readable text (dev) and
single-line JSON (prod, for ingestion by Datadog / Loki / ES).

Toggle via env var: LOG_FORMAT=text|json  (default depends on APP_ENV)

Design
──────
  • Stdlib `logging` only — no extra dependency.  Production log shippers
    universally consume stdout JSON.
  • Records emit a stable key set: timestamp, level, logger, message, plus
    any structured fields the caller attached via `extra={"key": value}`.
  • Uncaught exceptions in handlers serialise with exc_info as a list of
    strings; PII-free traceback context lives under `exception`.
  • Idempotent: configure_logging() may be called many times without
    duplicating handlers (the FastAPI lifespan and pytest both trigger it).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Dict

# Record attributes that are intrinsic to logging.LogRecord — anything else
# the user passed via `extra=...` is included as a structured field.
_STANDARD_RECORD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts":      time.strftime("%Y-%m-%dT%H:%M:%S",
                                     time.gmtime(record.created))
                       + f".{int(record.msecs):03d}Z",
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }

        # Surface anything the caller attached via `extra={...}`.
        for k, v in record.__dict__.items():
            if k in _STANDARD_RECORD_ATTRS or k.startswith("_"):
                continue
            payload[k] = _safe(v)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info

        return json.dumps(payload, default=str, ensure_ascii=False)


def _safe(value: Any) -> Any:
    """Coerce non-JSON-friendly values to strings."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    return str(value)


# ── public configure() — called once from main.py ─────────────────────────────

def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """
    Install a single stdout handler on the root logger.

    Calling more than once detaches the previous handler so we never double-
    log (matters in pytest, where the FastAPI lifespan boots per-test).
    """
    root = logging.getLogger()
    # Clear pre-existing handlers (we own root logging in this app).
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)

    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root.addHandler(handler)
    root.setLevel(level.upper())

    # Quiet down a couple of chatty libraries — they log INFO on every
    # request which is unwanted noise at production scale.
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
