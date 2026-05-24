"""
Integration-style route tests using FastAPI TestClient (synchronous).
Database is an in-memory SQLite fixture; external services are monkeypatched.
Routes are mounted at /api/v1.
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.db import Base, CompanyRecord, get_db
from backend.main import app

# All API routes live under this prefix
BASE = "/api/v1"


# ── In-memory SQLite fixture ──────────────────────────────────────────────────
@pytest.fixture()
def db_engine():
    # StaticPool ensures every connection uses the same in-memory database so
    # tables created by create_all() are visible to all subsequent sessions.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    """TestClient with the in-memory DB dependency override."""
    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    # Use raise_server_exceptions=False so we see the status code, not traceback
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────
def _make_company(db_session, ticker="AAPL", **kwargs):
    defaults = dict(
        name="Apple Inc", sector="Technology", sub_sector="Software",
        current_price=170.0, market_cap=2_700_000_000_000.0,
        risk_score=25.0, risk_label="Low Risk", risk_confidence=85.0,
        risk_flags="[]", risk_components="{}",
        upside_pct=15.0, valuation_label="Undervalued", valuation_confidence=70.0,
        composite_fair_value=195.0, dcf_fair_value=200.0,
        bear_target=140.0, base_target=195.0, bull_target=230.0,
        stretched_bull_target=260.0,
        entry_zone_low=160.0, entry_zone_high=175.0,
        trim_level=226.0, hard_stop=133.0,
        quality_score=77.8, quality_label="Strong", piotroski_f_score=7,
        graham_number=95.0,
        bcsi_score=72.5, bcsi_label="Strong",
        bcsi_dimensions=json.dumps({
            "risk":       {"score": 75.0, "weight": 0.294},
            "quality":    {"score": 77.8, "weight": 0.294},
            "valuation":  {"score": 65.0, "weight": 0.235},
            "governance": {"score": 82.0, "weight": 0.176},
        }),
        bcsi_confidence=80,
        last_updated=datetime.utcnow(),
    )
    defaults.update(kwargs)
    rec = CompanyRecord(ticker=ticker, **defaults)
    db_session.add(rec)
    db_session.commit()
    db_session.refresh(rec)
    return rec


# ── GET /companies/{ticker}/bcsi ──────────────────────────────────────────────
def test_bcsi_returns_score(client, db_session):
    _make_company(db_session)
    resp = client.get(f"{BASE}/companies/AAPL/bcsi")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["bcsi_score"] == 72.5
    assert data["bcsi_label"] == "Strong"
    assert data["bcsi_confidence"] == 80
    assert "risk" in data["dimensions"]
    assert "quality" in data["dimensions"]


def test_bcsi_includes_quality_breakdown(client, db_session):
    _make_company(db_session)
    data = client.get(f"{BASE}/companies/AAPL/bcsi").json()
    q = data["quality"]
    assert q["quality_score"] == 77.8
    assert q["quality_label"] == "Strong"
    assert q["piotroski_f_score"] == 7
    assert q["graham_number"] == 95.0


def test_bcsi_404_for_unknown_ticker(client):
    resp = client.get(f"{BASE}/companies/ZZZZ/bcsi")
    assert resp.status_code == 404


def test_bcsi_empty_dimensions_when_null(client, db_session):
    """A company with NULL bcsi_dimensions returns an empty dict, not an error."""
    _make_company(db_session, ticker="BARE", bcsi_dimensions=None)
    data = client.get(f"{BASE}/companies/BARE/bcsi").json()
    assert data["dimensions"] == {}


def test_bcsi_response_includes_momentum_block(client, db_session):
    _make_company(db_session)
    data = client.get(f"{BASE}/companies/AAPL/bcsi").json()
    assert "momentum" in data
    # Score may be None when no price history has been seeded, but the
    # nested block must always be present.
    assert "momentum_score" in data["momentum"]
    assert "components"     in data["momentum"]


# ── GET /companies/{ticker} includes BCSI in payload ─────────────────────────
def test_serialize_includes_bcsi_fields(client, db_session):
    _make_company(db_session)
    data = client.get(f"{BASE}/companies/AAPL").json()
    for field in (
        "bcsi_score", "bcsi_label", "bcsi_confidence", "bcsi_dimensions",
        "quality_score", "quality_label", "piotroski_f_score", "graham_number",
    ):
        assert field in data, f"missing field: {field}"


def test_serialize_bcsi_dimensions_is_dict(client, db_session):
    _make_company(db_session)
    data = client.get(f"{BASE}/companies/AAPL").json()
    assert isinstance(data["bcsi_dimensions"], dict)
    assert "risk" in data["bcsi_dimensions"]


# ── GET /companies lists companies with BCSI ──────────────────────────────────
def test_list_includes_bcsi(client, db_session):
    _make_company(db_session, ticker="T1", bcsi_label="Strong", bcsi_score=75.0)
    _make_company(db_session, ticker="T2", bcsi_label="Weak",   bcsi_score=32.0)
    data = client.get(f"{BASE}/companies").json()
    assert len(data) == 2
    tickers = {c["ticker"] for c in data}
    assert tickers == {"T1", "T2"}
    for c in data:
        assert "bcsi_score" in c
        assert "bcsi_label" in c


# ── GET /companies/{ticker} ───────────────────────────────────────────────────
def test_get_company_returns_record(client, db_session):
    _make_company(db_session)
    data = client.get(f"{BASE}/companies/AAPL").json()
    assert data["ticker"] == "AAPL"
    assert data["current_price"] == 170.0


def test_get_company_404(client):
    assert client.get(f"{BASE}/companies/XXXX").status_code == 404


def test_invalid_ticker_format_rejected(client):
    # Slashes are path separators; use a URL-encoded invalid char instead
    resp = client.get(f"{BASE}/companies/TICKER%21%21%21")  # "TICKER!!!"
    assert resp.status_code == 422
