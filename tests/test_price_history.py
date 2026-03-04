"""Tests for the price-history layer — price_on() and forward_return()."""

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.db import Base, PriceHistory
from backend.services.price_history import price_on, forward_return


@pytest.fixture
def db():
    """Throwaway in-memory SQLite session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed(db, ticker, rows):
    """rows: list of (date, close)."""
    for d, c in rows:
        db.add(PriceHistory(ticker=ticker, date=d, close=c, volume=1000.0))
    db.commit()


# ── price_on ──────────────────────────────────────────────────────────────────
def test_price_on_exact_date(db):
    _seed(db, "AAA", [(dt.date(2023, 1, 3), 100.0), (dt.date(2023, 1, 4), 102.0)])
    assert price_on(db, "AAA", dt.date(2023, 1, 4)) == 102.0


def test_price_on_falls_back_to_prior_close(db):
    # Market shut at the weekend — Sunday resolves to Friday's close.
    _seed(db, "AAA", [(dt.date(2023, 1, 6), 110.0)])      # a Friday
    assert price_on(db, "AAA", dt.date(2023, 1, 8)) == 110.0   # the Sunday


def test_price_on_returns_none_before_data(db):
    _seed(db, "AAA", [(dt.date(2023, 6, 1), 50.0)])
    assert price_on(db, "AAA", dt.date(2023, 1, 1)) is None


def test_price_on_is_ticker_scoped(db):
    _seed(db, "AAA", [(dt.date(2023, 1, 3), 100.0)])
    _seed(db, "BBB", [(dt.date(2023, 1, 3), 999.0)])
    assert price_on(db, "AAA", dt.date(2023, 1, 3)) == 100.0
    assert price_on(db, "BBB", dt.date(2023, 1, 3)) == 999.0


def test_price_on_tolerance_rejects_stale_data(db):
    _seed(db, "AAA", [(dt.date(2023, 1, 2), 100.0)])
    # 30 days later with a 10-day tolerance → too stale → None
    assert price_on(db, "AAA", dt.date(2023, 2, 1), tolerance_days=10) is None
    # within tolerance → returned
    assert price_on(db, "AAA", dt.date(2023, 1, 5), tolerance_days=10) == 100.0


# ── forward_return ────────────────────────────────────────────────────────────
def test_forward_return_positive(db):
    _seed(db, "AAA", [(dt.date(2023, 1, 2), 100.0), (dt.date(2024, 1, 2), 125.0)])
    assert forward_return(db, "AAA", dt.date(2023, 1, 2), months=12) == 25.0


def test_forward_return_negative(db):
    _seed(db, "AAA", [(dt.date(2023, 1, 2), 200.0), (dt.date(2023, 7, 2), 150.0)])
    assert forward_return(db, "AAA", dt.date(2023, 1, 2), months=6) == -25.0


def test_forward_return_none_when_horizon_runs_past_data(db):
    # Only a start price exists — the 12-month endpoint has no nearby data,
    # so the return is "not measurable", not a misleading 0%.
    _seed(db, "AAA", [(dt.date(2023, 1, 2), 100.0)])
    assert forward_return(db, "AAA", dt.date(2023, 1, 2), months=12) is None


# ── fetch_and_store_prices (yfinance mocked — no network) ─────────────────────
def test_fetch_and_store_prices_stores_and_skips_duplicates(db, monkeypatch):
    import pandas as pd
    from backend.services import price_history as ph

    fake_hist = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0], "Volume": [1e6, 1.1e6, 1.2e6]},
        index=pd.to_datetime(["2023-01-03", "2023-01-04", "2023-01-05"]),
    )

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            return fake_hist

    monkeypatch.setattr(ph.yf, "Ticker", FakeTicker)

    inserted = ph.fetch_and_store_prices(db, "AAA", years=1)
    assert inserted == 3
    assert price_on(db, "AAA", dt.date(2023, 1, 4)) == 101.0

    # Re-running must not duplicate rows already present.
    assert ph.fetch_and_store_prices(db, "AAA", years=1) == 0
