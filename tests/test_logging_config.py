"""
Tests for backend/logging_config.py.

The JSON formatter is what production log shippers consume — every assertion
here protects a downstream parser contract.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from backend.logging_config import JsonFormatter, configure_logging


# ── Pure formatter ────────────────────────────────────────────────────────────

def _make_record(**kw):
    """Build a LogRecord with the given overrides."""
    defaults = dict(
        name="test", level=logging.INFO, pathname=__file__,
        lineno=42, msg="hello %s", args=("world",), exc_info=None,
    )
    defaults.update(kw)
    return logging.LogRecord(**defaults)


def test_json_format_emits_required_keys():
    rec  = _make_record()
    line = JsonFormatter().format(rec)
    data = json.loads(line)
    for key in ("ts", "level", "logger", "message"):
        assert key in data, f"missing {key}: {data}"
    assert data["level"]   == "INFO"
    assert data["logger"]  == "test"
    assert data["message"] == "hello world"


def test_json_format_serialises_extra_fields():
    rec = _make_record()
    rec.request_id = "abc-123"
    rec.ticker     = "AAPL"
    data = json.loads(JsonFormatter().format(rec))
    assert data["request_id"] == "abc-123"
    assert data["ticker"]     == "AAPL"


def test_json_format_skips_standard_attrs():
    """Internal LogRecord fields like `pathname` must NOT leak into the JSON."""
    rec  = _make_record()
    data = json.loads(JsonFormatter().format(rec))
    for noisy in ("pathname", "args", "msecs", "filename", "module"):
        assert noisy not in data, f"unexpected key {noisy}: {data}"


def test_json_format_handles_exception_info():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        rec = _make_record(exc_info=sys.exc_info())
    data = json.loads(JsonFormatter().format(rec))
    assert "exception" in data
    assert "ValueError" in data["exception"]
    assert "boom" in data["exception"]


def test_json_format_handles_non_serialisable_extra():
    """Non-JSON values must fall back to str() rather than raising."""
    rec = _make_record()
    class _Weird:
        def __repr__(self): return "<Weird>"
    rec.weird = _Weird()
    data = json.loads(JsonFormatter().format(rec))
    assert data["weird"] == "<Weird>"


def test_json_format_each_record_is_one_line():
    """Crucial for line-delimited log shippers — no embedded newlines."""
    rec  = _make_record(msg="line1\nline2", args=())
    line = JsonFormatter().format(rec)
    # The serialised JSON itself should not span more than one physical line.
    assert "\n" not in line
    data = json.loads(line)
    # The embedded newline IS preserved inside the JSON-encoded string.
    assert "\n" in data["message"]


# ── configure_logging() ───────────────────────────────────────────────────────

def test_configure_text_mode_writes_human_readable():
    configure_logging(level="INFO", fmt="text")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    # Format string contains a level placeholder.
    assert "%(levelname)" in root.handlers[0].formatter._fmt


def test_configure_json_mode_uses_json_formatter():
    configure_logging(level="INFO", fmt="json")
    root = logging.getLogger()
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_is_idempotent():
    """Repeat calls must not stack handlers (otherwise we'd double-log)."""
    configure_logging(level="INFO", fmt="json")
    configure_logging(level="INFO", fmt="json")
    configure_logging(level="DEBUG", fmt="text")
    assert len(logging.getLogger().handlers) == 1


def test_configure_quiets_noisy_libraries():
    configure_logging(level="DEBUG", fmt="json")
    for noisy in ("uvicorn.access", "sqlalchemy.engine", "urllib3"):
        assert logging.getLogger(noisy).level == logging.WARNING


def test_configure_emits_json_to_stdout(capsys):
    configure_logging(level="INFO", fmt="json")
    log = logging.getLogger("test.emit")
    log.info("hello", extra={"ticker": "TSLA"})
    captured = capsys.readouterr()
    data = json.loads(captured.out.strip().splitlines()[-1])
    assert data["message"] == "hello"
    assert data["ticker"]  == "TSLA"
