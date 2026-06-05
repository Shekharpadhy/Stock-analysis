"""
Tests for backend/services/ticker_lookup.py and the GET /lookup endpoint.

The yfinance Search API is wrapped behind a thin adapter; we mock it so the
tests are deterministic and don't hit the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import Base, get_db
from backend.main import app
from backend.services import ticker_lookup


BASE = "/api/v1"


def _mock_search(quotes):
    """Build a fake yfinance.Search return value."""
    r = MagicMock()
    r.quotes = quotes
    return r


# ── pure scorer ───────────────────────────────────────────────────────────────

def test_search_returns_empty_for_short_query():
    assert ticker_lookup.search_tickers("") == []
    assert ticker_lookup.search_tickers("a") == []


def test_search_resolves_name_to_ticker():
    with patch("yfinance.Search", return_value=_mock_search([
        {"symbol": "AAPL",  "shortname": "Apple Inc.",
         "exchange": "NMS", "quoteType": "EQUITY"},
        {"symbol": "AAPL.MX","shortname": "Apple Inc.",
         "exchange": "MEX","quoteType": "EQUITY"},
    ])):
        out = ticker_lookup.search_tickers("Apple")
    assert len(out) == 2
    assert out[0]["ticker"] == "AAPL"
    assert out[0]["name"] == "Apple Inc."
    assert out[0]["exchange"] == "NMS"


def test_search_filters_non_equity_quote_types():
    """Futures, currencies, indices shouldn't pollute the dropdown."""
    with patch("yfinance.Search", return_value=_mock_search([
        {"symbol": "AAPL",   "shortname": "Apple Inc.",   "quoteType": "EQUITY"},
        {"symbol": "AAPL=X", "shortname": "Apple Future", "quoteType": "FUTURE"},
        {"symbol": "QQQ",    "shortname": "Invesco QQQ",  "quoteType": "ETF"},
    ])):
        out = ticker_lookup.search_tickers("Apple")
    tickers = [r["ticker"] for r in out]
    assert "AAPL" in tickers
    assert "QQQ"  in tickers
    assert "AAPL=X" not in tickers


def test_search_deduplicates_repeated_symbols():
    with patch("yfinance.Search", return_value=_mock_search([
        {"symbol": "AAPL", "shortname": "Apple",   "quoteType": "EQUITY"},
        {"symbol": "AAPL", "shortname": "Apple 2", "quoteType": "EQUITY"},
    ])):
        out = ticker_lookup.search_tickers("Apple")
    assert len(out) == 1


def test_search_respects_max_results():
    with patch("yfinance.Search", return_value=_mock_search([
        {"symbol": f"X{i}", "shortname": f"X{i}", "quoteType": "EQUITY"}
        for i in range(20)
    ])):
        out = ticker_lookup.search_tickers("Xx", max_results=3)
    assert len(out) == 3


def test_search_swallows_network_errors():
    """A broken yfinance call yields [], never an exception."""
    with patch("yfinance.Search", side_effect=RuntimeError("network down")):
        assert ticker_lookup.search_tickers("Apple") == []


def test_search_falls_back_for_ticker_when_yahoo_misses():
    """If the query looks like a ticker and Yahoo returns nothing, we still
    surface a minimal entry so the dashboard isn't empty."""
    with patch("yfinance.Search", return_value=_mock_search([])):
        out = ticker_lookup.search_tickers("AAPL")
    assert len(out) == 1
    assert out[0]["ticker"] == "AAPL"


def test_search_does_not_fallback_for_obvious_non_ticker():
    """For strings that don't look like tickers, an empty result stays empty."""
    with patch("yfinance.Search", return_value=_mock_search([])):
        out = ticker_lookup.search_tickers("xyz nonexistent")
    assert out == []


def test_resolve_to_ticker_returns_top_match():
    with patch("yfinance.Search", return_value=_mock_search([
        {"symbol": "AAPL", "shortname": "Apple Inc.", "quoteType": "EQUITY"},
        {"symbol": "AAPL.L","shortname": "Apple Inc.","quoteType": "EQUITY"},
    ])):
        assert ticker_lookup.resolve_to_ticker("Apple") == "AAPL"


def test_resolve_to_ticker_returns_none_on_no_match():
    with patch("yfinance.Search", return_value=_mock_search([])):
        assert ticker_lookup.resolve_to_ticker("xyzzy") is None


# ── /lookup endpoint ─────────────────────────────────────────────────────────

@pytest.fixture
def client():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)

    def _override():
        s = Session()
        try: yield s
        finally: s.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_lookup_endpoint_returns_array(client):
    with patch("yfinance.Search", return_value=_mock_search([
        {"symbol": "AAPL", "shortname": "Apple Inc.",
         "exchange": "NMS", "quoteType": "EQUITY"},
    ])):
        r = client.get(f"{BASE}/lookup?q=Apple")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["ticker"] == "AAPL"


def test_lookup_endpoint_empty_query(client):
    r = client.get(f"{BASE}/lookup?q=")
    assert r.status_code == 200
    assert r.json() == []


def test_lookup_endpoint_limit_clamped(client):
    """limit > 20 should be capped to 20 to keep the dropdown sane."""
    fake = [{"symbol": f"X{i}", "shortname": f"X{i}", "quoteType": "EQUITY"}
            for i in range(50)]
    with patch("yfinance.Search", return_value=_mock_search(fake)):
        r = client.get(f"{BASE}/lookup?q=X&limit=99")
    assert r.status_code == 200
    assert len(r.json()) <= 20
