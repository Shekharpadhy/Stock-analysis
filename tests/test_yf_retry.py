"""
Tests for backend.services.ingestion._safe_yf — the retry wrapper that
isolates yfinance's three known cloud-IP failure modes.

The point isn't to test yfinance.  The point is that our wrapper:
  • returns the result on first success
  • retries on any exception
  • returns `default` after persistent failure (never raises)
  • backs off exponentially between attempts
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from backend.services.ingestion import _safe_yf


def test_returns_value_on_first_success():
    getter = MagicMock(return_value={"quoteType": "EQUITY"})
    out = _safe_yf(getter)
    assert out == {"quoteType": "EQUITY"}
    assert getter.call_count == 1


def test_retries_on_attribute_error():
    """yfinance crashes with AttributeError on rate-limited partial responses."""
    getter = MagicMock(side_effect=[
        AttributeError("'NoneType' object has no attribute 'update'"),
        AttributeError("'NoneType' object has no attribute 'update'"),
        {"quoteType": "EQUITY"},   # succeeds on third try
    ])
    out = _safe_yf(getter, base_delay=0.0)
    assert out == {"quoteType": "EQUITY"}
    assert getter.call_count == 3


def test_retries_on_connection_error():
    getter = MagicMock(side_effect=[
        ConnectionError("rate limited"),
        {"data": "fine"},
    ])
    out = _safe_yf(getter, base_delay=0.0)
    assert out == {"data": "fine"}
    assert getter.call_count == 2


def test_returns_default_after_persistent_failure():
    """After attempts are exhausted, return the sentinel — never raise."""
    getter = MagicMock(side_effect=AttributeError("broken"))
    out = _safe_yf(getter, attempts=3, base_delay=0.0, default={"empty": True})
    assert out == {"empty": True}
    assert getter.call_count == 3


def test_default_when_getter_returns_none():
    """None means 'no data' too — retry, then fall back to default."""
    getter = MagicMock(return_value=None)
    out = _safe_yf(getter, attempts=3, base_delay=0.0, default="fallback")
    assert out == "fallback"
    assert getter.call_count == 3


def test_never_raises_to_caller():
    """The wrapper's whole job is to absorb errors so callers don't have
    to litter every yfinance access with try/except."""
    getter = MagicMock(side_effect=Exception("whatever"))
    # Should NOT raise.
    out = _safe_yf(getter, attempts=2, base_delay=0.0)
    assert out is None


def test_backoff_between_attempts(monkeypatch):
    """Calls sleep(0.5), sleep(1.0) between three attempts."""
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    getter = MagicMock(side_effect=AttributeError("bad"))
    _safe_yf(getter, attempts=3, base_delay=0.5)
    # 2 sleeps between 3 attempts; 0.5 * 2**0 and 0.5 * 2**1
    assert sleeps == [0.5, 1.0]


def test_single_attempt_no_sleep(monkeypatch):
    """attempts=1 should not call sleep at all."""
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    getter = MagicMock(side_effect=AttributeError("bad"))
    _safe_yf(getter, attempts=1, base_delay=0.5)
    assert sleeps == []
