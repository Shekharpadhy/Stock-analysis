"""
Tests for the Redis caching layer and the cached fetch_company_data().
Uses fakeredis so no real Redis server is needed.
"""

import fakeredis
import pytest

from backend.services import cache
from backend.services import ingestion


@pytest.fixture
def fake_redis(monkeypatch):
    """Inject an in-memory fake Redis client into the cache module."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache, "_client", fake)
    monkeypatch.setattr(cache, "_cooldown_until", 0.0)
    return fake


# ── Cache primitives ──────────────────────────────────────────────────────────
def test_set_then_get_roundtrip(fake_redis):
    cache.cache_set("k", {"a": 1, "b": [2, 3]}, ttl=60)
    assert cache.cache_get("k") == {"a": 1, "b": [2, 3]}


def test_get_miss_returns_none(fake_redis):
    assert cache.cache_get("not-there") is None


def test_cache_healthy_true_with_redis(fake_redis):
    assert cache.cache_healthy() is True


# ── Graceful degradation ──────────────────────────────────────────────────────
def test_no_crash_when_redis_unreachable(monkeypatch):
    """A down Redis must degrade to a silent no-op, never raise."""
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "_cooldown_until", 0.0)

    def boom(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(cache.redis.Redis, "from_url", boom)

    assert cache.cache_get("k") is None        # no exception
    cache.cache_set("k", {"x": 1}, ttl=60)     # no exception
    assert cache.cache_healthy() is False


# ── fetch_company_data caching behaviour ──────────────────────────────────────
def test_fetch_company_data_hits_cache_on_second_call(fake_redis, monkeypatch):
    """Second analysis of the same ticker must NOT re-hit yfinance."""
    calls = {"fetch": 0, "advanced": 0}

    def fake_fetch(ticker):
        calls["fetch"] += 1
        return ({"ticker": ticker, "sector": "Technology"}, object())

    def fake_advanced(_ticker_obj):
        calls["advanced"] += 1
        return {"altman": {}, "beneish": {}, "icr": None, "fcf_margin": None}

    monkeypatch.setattr(ingestion, "fetch_yahoo_fundamentals_full", fake_fetch)
    monkeypatch.setattr(ingestion, "compute_all_advanced", fake_advanced)

    first  = ingestion.fetch_company_data("AAPL")
    second = ingestion.fetch_company_data("AAPL")

    assert calls["fetch"] == 1        # yfinance hit exactly once
    assert calls["advanced"] == 1     # advanced scores computed once
    assert first == second            # cached payload equals the fresh one


def test_fetch_company_data_separate_keys_per_ticker(fake_redis, monkeypatch):
    calls = {"n": 0}

    def fake_fetch(ticker):
        calls["n"] += 1
        return ({"ticker": ticker}, object())

    monkeypatch.setattr(ingestion, "fetch_yahoo_fundamentals_full", fake_fetch)
    monkeypatch.setattr(ingestion, "compute_all_advanced", lambda _o: {"altman": {}})

    ingestion.fetch_company_data("AAPL")
    ingestion.fetch_company_data("MSFT")
    ingestion.fetch_company_data("AAPL")   # cached

    assert calls["n"] == 2                 # AAPL + MSFT fetched, AAPL reused
