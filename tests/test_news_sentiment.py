"""
Tests for backend/services/news_sentiment.py and its integration with
momentum.

Coverage
────────
  • Pure scorer: empty, all-positive, all-negative, mixed, single-headline
    damping, label boundaries
  • Tokenisation: punctuation, mixed case, compound phrases
  • Aggregate dict shape stays stable across input sizes
  • Momentum integration: news_score increases / decreases momentum, and
    confidence reflects the 5th component
  • fetch_headlines / compute_news_score swallow network errors
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch

import pytest

import backend.services.news_sentiment as ns
from backend.services import momentum as mom
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.database.db import Base, PriceHistory


# ── Pure scorer ───────────────────────────────────────────────────────────────

def test_empty_list_returns_unknown():
    out = ns.score_headlines([])
    assert out["score"] is None
    assert out["label"] == "Unknown"
    assert out["n"]     == 0


def test_all_positive_headlines_score_high():
    out = ns.score_headlines([
        "Company beats Q3 earnings; record revenue growth",
        "Apple upgraded by Morgan Stanley after dividend hike",
        "Strong profitable quarter; analyst raises price target",
        "Shares surge on robust outlook and approval of new product",
    ])
    assert out["score"] is not None
    assert out["score"] >= 70
    assert out["label"] in ("Bullish", "Positive")
    assert out["n_positive"] >= 3


def test_all_negative_headlines_score_low():
    out = ns.score_headlines([
        "SEC opens fraud investigation into accounting practices",
        "Company files for bankruptcy after delisted from exchange",
        "Restructuring brings layoffs; analyst downgrade follows weak guidance",
        "Restatement of prior earnings amid SEC probe",
    ])
    assert out["score"] is not None
    assert out["score"] <= 30
    assert out["label"] in ("Bearish", "Negative")
    assert out["n_negative"] >= 3


def test_mixed_headlines_score_neutral_ish():
    out = ns.score_headlines([
        "Stock falls on quarterly miss",
        "Analyst raises rating to outperform",
        "Bankruptcy concerns countered by debt buyback announcement",
    ])
    assert out["score"] is not None
    # Mixed sentiment — should land near the middle with damping.
    assert 35 < out["score"] < 65


def test_single_headline_is_damped():
    """One sensational headline shouldn't rail the score to 0 or 100."""
    out = ns.score_headlines(["Bankruptcy investigation fraud probe"])
    # raw_sum is heavily negative, but damping divisor is 5 → moderate dip
    assert 5 < out["score"] < 40


def test_tokenisation_handles_punctuation_and_case():
    s1, _ = ns._score_one("Beats! profits soar — STRONG growth")
    s2, _ = ns._score_one("beats profits soar strong growth")
    assert abs(s1 - s2) < 0.001


def test_compound_phrase_matches():
    s, matched = ns._score_one("Board approves dividend hike for shareholders")
    assert "dividend hike" in matched
    assert s > 0


def test_samples_field_limited_to_five():
    headlines = ["Earnings beat" for _ in range(10)] + \
                ["Bankruptcy concerns" for _ in range(10)]
    out = ns.score_headlines(headlines)
    assert len(out["samples"]) == 5


def test_samples_sorted_by_absolute_score():
    out = ns.score_headlines([
        "Stock up slightly",
        "SEC fraud investigation, bankruptcy concerns",   # huge negative
        "Modest positive guidance",
    ])
    # The strongest-signal headline must lead.
    assert "fraud" in out["samples"][0]["headline"].lower()


# ── fetch_headlines / compute_news_score ──────────────────────────────────────

def test_fetch_headlines_swallows_network_error():
    """A broken yfinance import or HTTP error must yield [] (never raise)."""
    with patch("yfinance.Ticker", side_effect=RuntimeError("network down")):
        assert ns.fetch_headlines("AAPL") == []


def test_compute_news_score_none_when_no_headlines():
    with patch.object(ns, "fetch_headlines", return_value=[]):
        assert ns.compute_news_score("AAPL") is None


def test_compute_news_score_end_to_end():
    fake_headlines = [
        "Earnings beat; analyst upgrade after record quarter",
        "Strong growth and profitable expansion",
    ]
    with patch.object(ns, "fetch_headlines", return_value=fake_headlines):
        out = ns.compute_news_score("AAPL")
    assert out is not None
    assert out["score"] > 60


# ── Momentum integration ─────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    sess = Session()
    yield sess
    sess.close()


def _seed_uptrend(db, ticker="AAPL"):
    end = dt.date(2026, 5, 25)
    rows = []
    for i in range(400):
        date = end - dt.timedelta(days=399 - i)
        close = 100.0 * (1.0 + 0.30 * i / 399)
        rows.append(PriceHistory(ticker=ticker, date=date,
                                 close=close, volume=1e6))
    db.add_all(rows); db.commit()
    return end


def test_momentum_includes_news_when_provided(db_session):
    as_of = _seed_uptrend(db_session)
    out = mom.compute_momentum(
        "AAPL", db_session, recommendation="buy", as_of=as_of,
        news_score=85.0, news_meta={"label": "Bullish"},
    )
    assert "news_sentiment" in out["components"]
    assert out["components"]["news_sentiment"] == 85.0
    assert out["confidence"] == 100        # 5/5 components present


def test_momentum_omits_news_when_not_provided(db_session):
    as_of = _seed_uptrend(db_session)
    out = mom.compute_momentum(
        "AAPL", db_session, recommendation="buy", as_of=as_of,
    )
    assert out["components"]["news_sentiment"] is None
    # 4/5 components present → 80% confidence
    assert out["confidence"] == 80


def test_bullish_news_lifts_momentum(db_session):
    as_of = _seed_uptrend(db_session)
    base    = mom.compute_momentum("AAPL", db_session, as_of=as_of)
    bullish = mom.compute_momentum("AAPL", db_session, as_of=as_of,
                                   news_score=90.0)
    bearish = mom.compute_momentum("AAPL", db_session, as_of=as_of,
                                   news_score=10.0)
    assert bullish["momentum_score"] > base["momentum_score"]
    assert bearish["momentum_score"] < base["momentum_score"]


def test_news_meta_surfaces_in_raw(db_session):
    as_of = _seed_uptrend(db_session)
    meta = {"label": "Bullish", "n": 3}
    out = mom.compute_momentum(
        "AAPL", db_session, as_of=as_of,
        news_score=80.0, news_meta=meta,
    )
    assert out["raw"]["news"] == meta
