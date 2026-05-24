"""
Unit tests for backend/services/price_stream.py

Tests cover:
  - ConnectionManager: connect / disconnect / broadcast / dead-conn pruning
  - send_snapshot with empty and populated DB
  - price_broadcast_loop: skips fetch when no clients, broadcasts when present
  - fetch_prices_batch: single-ticker and multi-ticker paths (mocked yfinance)

Async tests use asyncio.run() directly — no pytest-asyncio dependency needed.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.price_stream import (
    ConnectionManager,
    fetch_prices_batch,
    price_broadcast_loop,
    send_snapshot,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_ws(*, raises_on_send: bool = False) -> MagicMock:
    """Return a mock WebSocket that records sent messages."""
    ws = MagicMock()
    if raises_on_send:
        ws.send_text = AsyncMock(side_effect=RuntimeError("connection dead"))
    else:
        ws.send_text = AsyncMock()
    ws.accept = AsyncMock()
    return ws


def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ── ConnectionManager ─────────────────────────────────────────────────────────

def test_connect_adds_to_active():
    mgr = ConnectionManager()
    ws  = _mock_ws()
    run(mgr.connect(ws))
    assert mgr.count == 1
    ws.accept.assert_awaited_once()


def test_disconnect_removes_from_active():
    mgr = ConnectionManager()
    ws  = _mock_ws()
    run(mgr.connect(ws))
    mgr.disconnect(ws)
    assert mgr.count == 0


def test_broadcast_sends_to_all_clients():
    mgr = ConnectionManager()
    ws1, ws2 = _mock_ws(), _mock_ws()
    run(mgr.connect(ws1))
    run(mgr.connect(ws2))
    msg = {"type": "price_update", "data": []}
    run(mgr.broadcast(msg))
    ws1.send_text.assert_awaited_once_with(json.dumps(msg))
    ws2.send_text.assert_awaited_once_with(json.dumps(msg))


def test_broadcast_prunes_dead_connections():
    mgr  = ConnectionManager()
    live = _mock_ws()
    dead = _mock_ws(raises_on_send=True)
    run(mgr.connect(live))
    run(mgr.connect(dead))
    assert mgr.count == 2

    run(mgr.broadcast({"type": "heartbeat"}))

    # Dead connection pruned; live one stays
    assert mgr.count == 1
    live.send_text.assert_awaited_once()


def test_broadcast_no_clients_is_noop():
    mgr = ConnectionManager()
    # Should not raise, nothing to send
    run(mgr.broadcast({"type": "heartbeat"}))


def test_send_single_client():
    mgr = ConnectionManager()
    ws  = _mock_ws()
    run(mgr.connect(ws))
    msg = {"type": "price_snapshot", "data": []}
    run(mgr.send(ws, msg))
    ws.send_text.assert_awaited_once_with(json.dumps(msg))


def test_send_discards_dead_client():
    mgr = ConnectionManager()
    ws  = _mock_ws(raises_on_send=True)
    run(mgr.connect(ws))
    assert mgr.count == 1
    run(mgr.send(ws, {"type": "test"}))
    assert mgr.count == 0


# ── send_snapshot ─────────────────────────────────────────────────────────────

def test_send_snapshot_empty_db_sends_nothing(monkeypatch):
    """When no tickers are in DB, send_snapshot should not send anything."""
    ws  = _mock_ws()
    mgr = ConnectionManager()
    run(mgr.connect(ws))

    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = []
    mock_session_cls = MagicMock(return_value=mock_db)

    import backend.services.price_stream as ps
    # SessionLocal is lazily imported inside the function — patch at source
    monkeypatch.setattr("backend.database.db.SessionLocal", mock_session_cls)
    monkeypatch.setattr(ps, "manager", mgr)

    run(send_snapshot(ws))
    ws.send_text.assert_not_awaited()


def test_send_snapshot_sends_stored_prices(monkeypatch):
    ws  = _mock_ws()
    mgr = ConnectionManager()
    run(mgr.connect(ws))

    row1 = MagicMock(ticker="AAPL", current_price=170.0)
    row2 = MagicMock(ticker="MSFT", current_price=415.0)
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [row1, row2]
    mock_session_cls = MagicMock(return_value=mock_db)

    import backend.services.price_stream as ps
    monkeypatch.setattr("backend.database.db.SessionLocal", mock_session_cls)
    monkeypatch.setattr(ps, "manager", mgr)

    run(send_snapshot(ws))

    ws.send_text.assert_awaited_once()
    payload = json.loads(ws.send_text.call_args[0][0])
    assert payload["type"] == "price_snapshot"
    tickers_sent = {item["ticker"] for item in payload["data"]}
    assert tickers_sent == {"AAPL", "MSFT"}


# ── fetch_prices_batch ────────────────────────────────────────────────────────

def test_fetch_prices_batch_empty_list():
    assert fetch_prices_batch([]) == {}


def test_fetch_prices_batch_single_ticker(monkeypatch):
    """Single-ticker path: Close is a Series."""
    import pandas as pd
    series = pd.Series([170.0, 171.5, 172.0])
    mock_data = MagicMock()
    mock_data.empty = False
    mock_data.__getitem__ = lambda self, key: series
    monkeypatch.setattr("yfinance.download", lambda *a, **kw: mock_data)

    result = fetch_prices_batch(["AAPL"])
    assert result == {"AAPL": 172.0}


def test_fetch_prices_batch_multi_ticker(monkeypatch):
    """Multi-ticker path: Close is a DataFrame."""
    import pandas as pd
    closes = pd.DataFrame({"AAPL": [170.0, 171.0], "MSFT": [415.0, 416.0]})
    mock_data = MagicMock()
    mock_data.empty = False
    mock_data.__getitem__ = lambda self, key: closes
    monkeypatch.setattr("yfinance.download", lambda *a, **kw: mock_data)

    result = fetch_prices_batch(["AAPL", "MSFT"])
    assert result["AAPL"] == 171.0
    assert result["MSFT"] == 416.0


def test_fetch_prices_batch_handles_exception(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("API down")
    monkeypatch.setattr("yfinance.download", _boom)
    assert fetch_prices_batch(["AAPL"]) == {}


# ── price_broadcast_loop ──────────────────────────────────────────────────────

def test_broadcast_loop_skips_fetch_when_no_clients(monkeypatch):
    """With zero connected clients the loop must not call yfinance."""
    import backend.services.price_stream as ps

    mgr = ConnectionManager()           # empty
    monkeypatch.setattr(ps, "manager", mgr)

    fetch_called = {"n": 0}
    def _no_fetch(*a, **kw):
        fetch_called["n"] += 1
        return {}
    monkeypatch.setattr(ps, "fetch_prices_batch", _no_fetch)

    sleep_count = {"n": 0}
    async def _fast_sleep(t):
        sleep_count["n"] += 1
        if sleep_count["n"] >= 2:
            raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    with pytest.raises(asyncio.CancelledError):
        run(price_broadcast_loop())

    assert fetch_called["n"] == 0, "yfinance must not be called when no clients"


def test_broadcast_loop_broadcasts_when_clients_present(monkeypatch):
    """With connected clients the loop fetches prices and broadcasts."""
    import backend.services.price_stream as ps

    ws  = _mock_ws()
    mgr = ConnectionManager()
    run(mgr.connect(ws))
    monkeypatch.setattr(ps, "manager", mgr)

    row = MagicMock(ticker="AAPL", current_price=170.0)
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [row]
    monkeypatch.setattr("backend.database.db.SessionLocal", MagicMock(return_value=mock_db))

    # asyncio.to_thread can't run in a test event loop easily — patch it
    async def _fake_to_thread(fn, *a, **kw):
        return {"AAPL": 172.0}
    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    sleep_count = {"n": 0}
    async def _fast_sleep(t):
        sleep_count["n"] += 1
        if sleep_count["n"] >= 2:
            raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

    with pytest.raises(asyncio.CancelledError):
        run(price_broadcast_loop())

    ws.send_text.assert_awaited()
    last_msg = json.loads(ws.send_text.call_args_list[-1][0][0])
    assert last_msg["type"] == "price_update"
    assert last_msg["data"][0]["ticker"] == "AAPL"
    assert last_msg["data"][0]["price"] == 172.0
    # change_pct = (172 - 170) / 170 * 100 ≈ 1.18
    assert last_msg["data"][0]["change_pct"] == pytest.approx(1.18, abs=0.01)
