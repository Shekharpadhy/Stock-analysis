"""
Unit tests for backend/services/ml_model.py

Tests cover:
  - Feature extraction + label building from synthetic DB records
  - Model training produces valid metadata and AUC
  - Prediction returns correct shape (probability, SHAP, drivers)
  - Edge cases: not-enough-data, unknown ticker, model-not-loaded
  - Persistence: save to disk, reload, and status check
"""

import os
import tempfile
from typing import List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import backend.services.ml_model as ml


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_company(ticker: str, altman_zone: str = "Safe", **overrides) -> MagicMock:
    """Synthetic CompanyRecord mock with sensible defaults."""
    defaults = dict(
        ticker=ticker,
        altman_zone=altman_zone,
        debt_to_equity=0.5,
        current_ratio=2.0,
        icr=8.0,
        fcf_margin=12.0,
        net_margin=15.0,
        roa=8.0,
        roe=18.0,
        revenue_growth_yoy=10.0,
        pe_ratio=22.0,
        ev_ebitda=14.0,
        altman_z_score=3.5,
        beneish_m_score=-2.5,
        risk_score=25.0,
        quality_score=70.0,
    )
    defaults.update(overrides)
    rec = MagicMock()
    for k, v in defaults.items():
        setattr(rec, k, v)
    return rec


def _make_db(companies: list, observations: Optional[List] = None) -> MagicMock:
    """Mock SQLAlchemy Session that returns synthetic data."""
    db = MagicMock()

    def _query_side_effect(model, *a, **kw):
        q = MagicMock()
        name = getattr(model, "__tablename__", None) or str(model)

        if "CompanyRecord" in str(model):
            q.filter.return_value.all.return_value = companies
            q.filter.return_value.first.side_effect = (
                lambda: next((c for c in companies), None)
            )
            q.all.return_value = companies
        elif "BacktestObservation" in str(model):
            obs = observations or []
            q.filter.return_value.all.return_value = obs
        else:
            q.filter.return_value.all.return_value = []
            q.all.return_value = []
        return q

    db.query.side_effect = _query_side_effect
    return db


def _healthy_companies(n: int = 30) -> list:
    """
    Generate n companies: first 6 are clearly distressed, rest are clearly safe.
    Use 6 separating features so XGBoost can reliably learn the boundary.
    """
    companies = []
    for i in range(n):
        distress = i < 6
        zone     = "Distress" if distress else "Safe"
        companies.append(_make_company(
            f"T{i}",
            altman_zone      = zone,
            risk_score       = 82.0  if distress else 18.0,
            altman_z_score   = 0.5   if distress else 4.0,
            debt_to_equity   = 4.5   if distress else 0.4,
            current_ratio    = 0.6   if distress else 2.5,
            icr              = 0.7   if distress else 9.0,
            net_margin       = -18.0 if distress else 16.0,
        ))
    return companies


# ── status before training ────────────────────────────────────────────────────

def test_status_returns_not_loaded_before_training():
    # Reset bundle
    ml._bundle = None
    status = ml.get_model_status()
    assert status["loaded"] is False
    assert status["meta"] is None


# ── training ──────────────────────────────────────────────────────────────────

def test_train_raises_when_insufficient_data():
    ml._bundle = None
    db = _make_db([_make_company("AAPL")])   # only 1 row — well below MIN_SAMPLES
    with pytest.raises(ValueError, match="Not enough"):
        ml.train(db)


def test_train_succeeds_with_enough_companies(tmp_path, monkeypatch):
    ml._bundle = None
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.joblib"))

    db = _make_db(_healthy_companies())
    meta = ml.train(db)

    assert meta["n_samples"] == 30
    assert meta["n_distress"] == 6
    assert meta["n_healthy"] == 24
    assert 0.0 <= meta["cv_auc"] <= 1.0
    assert set(meta["feature_cols"]) == set(ml.FEATURE_COLS)
    assert ml._bundle is not None
    assert os.path.exists(str(tmp_path / "model.joblib"))


def test_train_sets_status_to_loaded(tmp_path, monkeypatch):
    ml._bundle = None
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.joblib"))
    db = _make_db(_healthy_companies())
    ml.train(db)
    assert ml.get_model_status()["loaded"] is True


def test_train_feature_importance_covers_all_features(tmp_path, monkeypatch):
    ml._bundle = None
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.joblib"))
    db = _make_db(_healthy_companies())
    meta = ml.train(db)
    assert set(meta["feature_importance"].keys()) == set(ml.FEATURE_COLS)


# ── prediction ────────────────────────────────────────────────────────────────

def test_predict_raises_when_model_not_loaded():
    ml._bundle = None
    db = _make_db([_make_company("AAPL")])
    with pytest.raises(ValueError, match="No ML model"):
        ml.predict("AAPL", db)


def test_predict_raises_for_unknown_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.joblib"))
    db_train = _make_db(_healthy_companies())
    ml.train(db_train)

    # db returns None for the ticker query
    db_pred = MagicMock()
    q = MagicMock()
    q.filter.return_value.first.return_value = None
    db_pred.query.return_value = q

    from backend.database.db import CompanyRecord
    with pytest.raises(ValueError, match="not found"):
        ml.predict("ZZZZ", db_pred)


def test_predict_returns_probability_in_range(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.joblib"))
    db_train = _make_db(_healthy_companies())
    ml.train(db_train)

    company = _make_company("AAPL", altman_zone="Safe", risk_score=20.0)
    db_pred = MagicMock()
    q = MagicMock()
    q.filter.return_value.first.return_value = company
    db_pred.query.return_value = q

    result = ml.predict("AAPL", db_pred)
    assert 0.0 <= result["distress_probability"] <= 1.0
    assert result["distress_label"] in (
        "Low Distress Risk", "Moderate Distress Risk", "High Distress Risk"
    )


def test_predict_shap_values_cover_all_features(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.joblib"))
    db_train = _make_db(_healthy_companies())
    ml.train(db_train)

    company = _make_company("AAPL")
    db_pred = MagicMock()
    q = MagicMock()
    q.filter.return_value.first.return_value = company
    db_pred.query.return_value = q

    result = ml.predict("AAPL", db_pred)
    assert set(result["shap_values"].keys()) == set(ml.FEATURE_COLS)


def test_predict_top_drivers_sorted_by_abs_shap(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.joblib"))
    db_train = _make_db(_healthy_companies())
    ml.train(db_train)

    company = _make_company("AAPL")
    db_pred = MagicMock()
    q = MagicMock()
    q.filter.return_value.first.return_value = company
    db_pred.query.return_value = q

    result = ml.predict("AAPL", db_pred)
    drivers = result["top_drivers"]
    assert len(drivers) == 5
    abs_shaps = [abs(d["shap"]) for d in drivers]
    assert abs_shaps == sorted(abs_shaps, reverse=True)


def test_predict_high_risk_company_has_higher_prob(tmp_path, monkeypatch):
    """A company with Distress Altman zone should score higher than a safe one."""
    monkeypatch.setattr(ml, "MODEL_PATH", str(tmp_path / "model.joblib"))
    db_train = _make_db(_healthy_companies())
    ml.train(db_train)

    def _pred(distressed: bool):
        if distressed:
            company = _make_company(
                "X", altman_zone="Distress",
                risk_score=82.0, altman_z_score=0.5,
                debt_to_equity=4.5, current_ratio=0.6,
                icr=0.7, net_margin=-18.0,
            )
        else:
            company = _make_company(
                "X", altman_zone="Safe",
                risk_score=18.0, altman_z_score=4.0,
                debt_to_equity=0.4, current_ratio=2.5,
                icr=9.0, net_margin=16.0,
            )
        db_pred = MagicMock()
        q = MagicMock()
        q.filter.return_value.first.return_value = company
        db_pred.query.return_value = q
        return ml.predict("X", db_pred)["distress_probability"]

    distress_prob = _pred(True)
    safe_prob     = _pred(False)
    assert distress_prob > safe_prob


# ── model persistence ─────────────────────────────────────────────────────────

def test_load_model_from_disk_false_when_missing(monkeypatch):
    ml._bundle = None
    monkeypatch.setattr(ml, "MODEL_PATH", "/nonexistent/path/model.joblib")
    result = ml.load_model_from_disk()
    assert result is False
    assert ml._bundle is None


def test_load_model_from_disk_roundtrip(tmp_path, monkeypatch):
    path = str(tmp_path / "model.joblib")
    monkeypatch.setattr(ml, "MODEL_PATH", path)
    db = _make_db(_healthy_companies())
    ml.train(db)

    # Reset bundle and reload from disk
    ml._bundle = None
    result = ml.load_model_from_disk()
    assert result is True
    assert ml._bundle is not None
    assert ml._bundle["meta"]["n_samples"] == 30
