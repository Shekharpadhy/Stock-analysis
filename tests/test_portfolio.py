"""
Tests for portfolio analytics (Task #32).

Two surfaces are covered:
  • The pure aggregation function backend.services.portfolio.summarise()
  • The GET /users/me/portfolio endpoint (watchlist join + summary)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import (
    Base, get_db, User, CompanyRecord, WatchlistEntry,
)
from backend.main import app
from backend.services import portfolio as portfolio_svc


BASE = "/api/v1"


# ── pure summarise() tests ────────────────────────────────────────────────────

def _rec(**kwargs) -> SimpleNamespace:
    """Cheap CompanyRecord stand-in — summarise() reads attributes only."""
    defaults = dict(
        ticker="X", name="X Inc", sector="Tech",
        bcsi_score=None, bcsi_label=None,
        risk_score=None, momentum_score=None, momentum_label=None,
        altman_zone=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_summarise_empty():
    out = portfolio_svc.summarise([])
    assert out["coverage"] == 0
    assert out["data_coverage_pct"] == 0
    assert out["highlights"]["strongest"] == []
    assert out["highlights"]["weakest"] == []
    assert out["bcsi"]["mean"] is None


def test_summarise_single_strong_company():
    rec = _rec(ticker="AAPL", bcsi_score=82.0, bcsi_label="Strong",
               risk_score=15.0, momentum_score=78.0, momentum_label="Strong",
               altman_zone="Safe")
    out = portfolio_svc.summarise([rec])
    assert out["coverage"] == 1
    assert out["data_coverage_pct"] == 100
    assert out["bcsi"]["mean"] == 82.0
    assert out["bcsi"]["label_distribution"] == {"Strong": 1}
    assert out["risk"]["distribution"] == {"Low": 1}
    assert out["altman_zones"] == {"Safe": 1}
    assert out["highlights"]["strongest"][0]["ticker"] == "AAPL"


def test_summarise_mixed_portfolio_distributions():
    recs = [
        _rec(ticker="A", sector="Tech",     bcsi_score=82, bcsi_label="Strong",
             risk_score=15, momentum_score=80, momentum_label="Strong",
             altman_zone="Safe"),
        _rec(ticker="B", sector="Tech",     bcsi_score=61, bcsi_label="Fair",
             risk_score=45, momentum_score=55, momentum_label="Positive",
             altman_zone="Safe"),
        _rec(ticker="C", sector="Finance",  bcsi_score=45, bcsi_label="Watch",
             risk_score=68, momentum_score=35, momentum_label="Negative",
             altman_zone="Grey"),
        _rec(ticker="D", sector="Energy",   bcsi_score=28, bcsi_label="Weak",
             risk_score=88, momentum_score=12, momentum_label="Weak",
             altman_zone="Distress"),
    ]
    out = portfolio_svc.summarise(recs)
    assert out["coverage"] == 4
    assert out["data_coverage_pct"] == 100
    # Mean BCSI = (82+61+45+28)/4 = 54.0
    assert out["bcsi"]["mean"] == 54.0
    assert out["bcsi"]["min"] == 28
    assert out["bcsi"]["max"] == 82
    assert out["bcsi"]["label_distribution"] == {
        "Strong": 1, "Fair": 1, "Watch": 1, "Weak": 1,
    }
    assert out["risk"]["distribution"] == {"Low": 1, "Medium": 1, "High": 2}
    assert out["altman_zones"]["Distress"] == 1
    assert out["sector_exposure"] == {"Tech": 2, "Finance": 1, "Energy": 1}
    # Sector exposure must be sorted desc by count.
    keys = list(out["sector_exposure"].keys())
    assert keys[0] == "Tech"

    strongest = [h["ticker"] for h in out["highlights"]["strongest"]]
    weakest   = [h["ticker"] for h in out["highlights"]["weakest"]]
    assert strongest[0] == "A"
    assert weakest[0]   == "D"


def test_summarise_handles_partial_coverage():
    """Two of three tickers lack a BCSI score → coverage 33%, but the
    aggregator must NOT crash and must still report the one scored row."""
    recs = [
        _rec(ticker="A", bcsi_score=75.0, bcsi_label="Strong"),
        _rec(ticker="B"),
        _rec(ticker="C"),
    ]
    out = portfolio_svc.summarise(recs)
    assert out["coverage"] == 3
    assert out["data_coverage_pct"] == 33
    assert out["bcsi"]["mean"] == 75.0


def test_summarise_highlights_skip_unscored():
    recs = [
        _rec(ticker="SCORED", bcsi_score=60.0, bcsi_label="Fair"),
        _rec(ticker="NOSCORE"),
    ]
    out = portfolio_svc.summarise(recs)
    strongest = [h["ticker"] for h in out["highlights"]["strongest"]]
    assert "NOSCORE" not in strongest


# ── /users/me/portfolio endpoint ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def db_engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    sess = Session()
    yield sess
    sess.rollback()
    for tbl in (WatchlistEntry, CompanyRecord, User):
        sess.query(tbl).delete()
    sess.commit()
    sess.close()


@pytest.fixture
def client(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _register_login(client, username, email):
    client.post(f"{BASE}/auth/register",
                json={"username": username, "email": email,
                      "password": "Passw0rd!"})
    resp = client.post(f"{BASE}/auth/login",
                       json={"username": username, "email": "u@x",
                             "password": "Passw0rd!"})
    return resp.json()["access_token"]


def _seed_company(db, ticker, **kwargs):
    defaults = dict(
        ticker=ticker, name=ticker, sector="Tech",
        bcsi_score=60.0, bcsi_label="Fair",
        risk_score=40.0, momentum_score=55.0, momentum_label="Positive",
        altman_zone="Safe",
    )
    defaults.update(kwargs)
    db.add(CompanyRecord(**defaults))
    db.commit()


def test_portfolio_empty_when_no_watchlist(client):
    token = _register_login(client, "p_empty", "p_empty@example.com")
    resp = client.get(f"{BASE}/users/me/portfolio",
                      headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["coverage"] == 0
    assert data["missing_data"] == []


def test_portfolio_summarises_watchlist(client, db_session):
    _seed_company(db_session, "AAPL", bcsi_score=80.0, bcsi_label="Strong")
    _seed_company(db_session, "TSLA", bcsi_score=35.0, bcsi_label="Weak",
                  sector="Auto")

    token = _register_login(client, "p_user", "p_user@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    for t in ["AAPL", "TSLA"]:
        client.post(f"{BASE}/users/me/watchlist",
                    json={"ticker": t}, headers=headers)

    resp = client.get(f"{BASE}/users/me/portfolio", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["coverage"] == 2
    assert data["data_coverage_pct"] == 100
    assert data["bcsi"]["mean"] == 57.5
    assert set(data["sector_exposure"]) == {"Tech", "Auto"}
    assert data["missing_data"] == []


def test_portfolio_flags_missing_company_data(client, db_session):
    _seed_company(db_session, "AAPL", bcsi_score=80.0, bcsi_label="Strong")
    # TSLA in watchlist but no CompanyRecord seeded.

    token = _register_login(client, "p_missing", "p_missing@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    for t in ["AAPL", "TSLA"]:
        client.post(f"{BASE}/users/me/watchlist",
                    json={"ticker": t}, headers=headers)

    data = client.get(f"{BASE}/users/me/portfolio", headers=headers).json()
    assert "TSLA" in data["missing_data"]
    # `coverage` is per scored rows; missing tickers are accounted separately
    assert data["coverage"] == 1


def test_portfolio_requires_auth(client):
    resp = client.get(f"{BASE}/users/me/portfolio")
    assert resp.status_code == 401
