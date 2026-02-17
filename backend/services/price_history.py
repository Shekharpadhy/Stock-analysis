"""
Historical daily price ingestion and lookup.

Provides the price layer that both the backtesting harness and the live
self-scoring track record depend on. Prices come from yfinance and are stored
in the price_history table so backtests don't re-hit the network on every run.

Stored closes are split/dividend-adjusted (yfinance auto_adjust=True) — the
correct basis for measuring forward total return.
"""

import datetime as dt
from typing import Optional

import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from backend.database.db import PriceHistory


def fetch_and_store_prices(db: Session, ticker: str, years: int = 5) -> int:
    """
    Fetch up to `years` of daily closes from yfinance and store any dates not
    already present. Returns the number of new rows inserted.
    """
    ticker = ticker.upper()
    hist = yf.Ticker(ticker).history(period=f"{years}y", auto_adjust=True)
    if hist is None or hist.empty:
        return 0

    existing = {
        d for (d,) in db.query(PriceHistory.date)
                        .filter(PriceHistory.ticker == ticker).all()
    }

    inserted = 0
    for idx, row in hist.iterrows():
        day = idx.date() if hasattr(idx, "date") else idx
        if day in existing:
            continue
        close = row.get("Close")
        if close is None or pd.isna(close):
            continue
        vol = row.get("Volume")
        db.add(PriceHistory(
            ticker=ticker,
            date=day,
            close=float(close),
            volume=None if (vol is None or pd.isna(vol)) else float(vol),
        ))
        inserted += 1

    db.commit()
    return inserted


def price_on(
    db: Session,
    ticker: str,
    target_date: dt.date,
    tolerance_days: Optional[int] = None,
) -> Optional[float]:
    """
    Closing price on `target_date`, or the most recent close before it
    (markets are shut on weekends/holidays).

    If `tolerance_days` is given, return None when the nearest available close
    is older than that many days — i.e. when there is no real data near the
    requested date (rather than silently using a stale price).
    """
    row = (db.query(PriceHistory)
             .filter(PriceHistory.ticker == ticker.upper(),
                     PriceHistory.date <= target_date)
             .order_by(PriceHistory.date.desc())
             .first())
    if row is None:
        return None
    if tolerance_days is not None and (target_date - row.date).days > tolerance_days:
        return None
    return row.close


def forward_return(
    db: Session,
    ticker: str,
    from_date: dt.date,
    months: int,
    tolerance_days: int = 10,
) -> Optional[float]:
    """
    Percentage price return over `months` starting at `from_date`.

    Returns None if either endpoint lacks price data within `tolerance_days`
    of the requested date — so a horizon that runs past the available history
    is correctly reported as "not measurable" rather than 0%.
    """
    start = price_on(db, ticker, from_date, tolerance_days)
    end = price_on(db, ticker, from_date + relativedelta(months=months), tolerance_days)
    if start is None or end is None or start == 0:
        return None
    return round((end - start) / start * 100.0, 2)


def trailing_high_low(
    db: Session,
    ticker: str,
    as_of: dt.date,
    days: int = 365,
) -> tuple[Optional[float], Optional[float]]:
    """Highest and lowest close over the `days` window ending at `as_of`."""
    start = as_of - dt.timedelta(days=days)
    closes = [
        c for (c,) in db.query(PriceHistory.close)
                        .filter(PriceHistory.ticker == ticker.upper(),
                                PriceHistory.date > start,
                                PriceHistory.date <= as_of).all()
    ]
    if not closes:
        return None, None
    return max(closes), min(closes)
