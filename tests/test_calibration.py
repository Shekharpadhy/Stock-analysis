"""Tests for engine calibration — sector profile recalibration."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import datetime as dt

from backend.database.db import Base, CompanyRecord, SectorProfile, BacktestObservation
from backend.services.calibration import (
    recalibrate_sector_profiles, get_calibrated_profiles, _robust_spread,
    reliability_report,
)
from backend.services.ensemble_risk import SECTOR_RISK_PROFILES

_METRIC_NAMES = {"debt_to_equity", "current_ratio", "net_margin",
                 "revenue_growth_yoy", "pe_ratio", "roe", "beta"}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_companies(db, sector, n, prefix):
    for i in range(n):
        db.add(CompanyRecord(
            ticker=f"{prefix}{i}", sector=sector,
            debt_to_equity=50 + i * 5, current_ratio=1.5 + i * 0.1,
            net_margin=10 + i, revenue_growth_yoy=5 + i,
            pe_ratio=15 + i, roe=12 + i, beta=1.0 + i * 0.05,
        ))
    db.commit()


# ── _robust_spread ────────────────────────────────────────────────────────────
def test_robust_spread_floors_on_constant_data():
    # Constant data → IQR is 0 → spread floored to 15% of the median.
    assert _robust_spread([50.0] * 10) == pytest.approx(7.5)


def test_robust_spread_grows_with_dispersion():
    tight = _robust_spread([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    wide  = _robust_spread([10, 40, 70, 100, 130, 160, 190, 220, 250, 280])
    assert wide > tight


# ── recalibrate_sector_profiles ───────────────────────────────────────────────
def test_recalibrate_only_calibrates_sectors_with_enough_data(db):
    _seed_companies(db, "Information Technology", 10, "IT")
    _seed_companies(db, "Energy", 3, "EN")          # below the min sample
    result = recalibrate_sector_profiles(db)
    assert "Information Technology" in result["calibrated_sectors"]
    assert "Energy" not in result["calibrated_sectors"]

    rows = db.query(SectorProfile).all()
    assert rows and all(r.sector == "Information Technology" for r in rows)
    assert {r.metric for r in rows} == _METRIC_NAMES


def test_recalibrate_is_idempotent(db):
    _seed_companies(db, "Information Technology", 10, "IT")
    recalibrate_sector_profiles(db)
    n1 = db.query(SectorProfile).count()
    recalibrate_sector_profiles(db)                 # second run — upsert
    n2 = db.query(SectorProfile).count()
    assert n1 == n2 == len(_METRIC_NAMES)


# ── get_calibrated_profiles ───────────────────────────────────────────────────
def test_get_calibrated_profiles_falls_back_to_hardcoded(db):
    profiles = get_calibrated_profiles(db)          # no SectorProfile rows
    assert profiles["Information Technology"] == \
           SECTOR_RISK_PROFILES["Information Technology"]


def test_get_calibrated_profiles_overrides_with_data(db):
    _seed_companies(db, "Information Technology", 10, "IT")
    recalibrate_sector_profiles(db)
    profiles = get_calibrated_profiles(db)
    # Seeded D/E values (50..95) → calibrated median differs from the estimate.
    assert profiles["Information Technology"]["debt_to_equity"] != \
           SECTOR_RISK_PROFILES["Information Technology"]["debt_to_equity"]
    # Untouched sectors still carry the hardcoded estimate.
    assert profiles["Utilities"] == SECTOR_RISK_PROFILES["Utilities"]


# ── profiles override actually changes the risk engine output ─────────────────
def test_profiles_override_changes_risk_score():
    from backend.services.ensemble_risk import compute_ensemble_risk

    data = {"debt_to_equity": 300, "current_ratio": 1.5, "net_margin": 10,
            "revenue_growth_yoy": 5, "pe_ratio": 18, "roe": 12, "beta": 1.0}
    advanced = {"altman": {"zone": "Unavailable", "z_score": None},
                "beneish": {"flag": "Unavailable", "m_score": None},
                "icr": None, "fcf_margin": None}

    # Hardcoded Industrials D/E estimate is ~90 → 300 looks very risky.
    default = compute_ensemble_risk(data, advanced, "Industrials")
    # A calibrated profile where the sector median D/E IS 300 → now typical.
    custom = {"Industrials": {
        "debt_to_equity": (300.0, 80.0), "current_ratio": (1.5, 0.6),
        "net_margin": (10.0, 6.0), "revenue_growth_yoy": (5.0, 8.0),
        "pe_ratio": (18.0, 9.0), "roe": (12.0, 10.0), "beta": (1.0, 0.3)}}
    calibrated = compute_ensemble_risk(data, advanced, "Industrials", profiles=custom)

    assert calibrated["composite_score"] < default["composite_score"]


# ── reliability_report ────────────────────────────────────────────────────────
def _seed_observation(db, risk_score, forward_return):
    db.add(BacktestObservation(
        ticker="X", fy_end=dt.date(2022, 12, 31), as_of=dt.date(2023, 3, 31),
        sector="Industrials", horizon_months=12, risk_score=risk_score,
        risk_label="High Risk" if risk_score >= 60 else "Low Risk",
        valuation_label="Fairly Valued", upside_pct=0.0, base_target=100.0,
        price_at_as_of=100.0, forward_return_pct=forward_return,
    ))


def test_reliability_report_empty(db):
    r = reliability_report(db)
    assert r["n"] == 0
    assert "No measurable backtest observations" in r["verdict"]


def test_reliability_report_detects_well_calibrated(db):
    # Score-80 cohort: 8 of 10 actually had bad outcomes  → predicted 0.8 ≈ 0.8.
    for _ in range(8):
        _seed_observation(db, 80.0, -30.0)
    for _ in range(2):
        _seed_observation(db, 80.0, 10.0)
    # Score-20 cohort: 2 of 10 had bad outcomes → predicted 0.2 ≈ 0.2.
    for _ in range(2):
        _seed_observation(db, 20.0, -30.0)
    for _ in range(8):
        _seed_observation(db, 20.0, 10.0)
    db.commit()
    r = reliability_report(db)
    assert r["n"] == 20
    assert "Well-calibrated" in r["verdict"]


def test_reliability_report_detects_overconfidence(db):
    # Score-80 cohort but only 1 of 10 actually had a bad outcome → cries wolf.
    for _ in range(1):
        _seed_observation(db, 80.0, -30.0)
    for _ in range(9):
        _seed_observation(db, 80.0, 12.0)
    db.commit()
    r = reliability_report(db)
    assert "Overconfident" in r["verdict"]
    assert r["overall_gap"] > 0.1
