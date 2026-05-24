"""
ML-based default / financial-distress prediction.

Model
─────
XGBoost binary classifier trained on CompanyRecord fundamentals.

Target variable (two-tier approach)
────────────────────────────────────
  1. If ≥ MIN_OBS scored BacktestObservation rows exist, use actual forward
     returns: forward_return_pct < DISTRESS_RETURN_THRESHOLD → distress=1.
  2. Otherwise fall back to Altman zone: zone == "Distress" → distress=1.

Features (FEATURE_COLS)
───────────────────────
  Fourteen fundamental + model-output features drawn from CompanyRecord.
  NaN values are imputed with column medians; features are not scaled
  (XGBoost handles arbitrary scales natively).

Explainability
──────────────
  SHAP TreeExplainer produces per-prediction feature attributions.  The
  caller receives the raw SHAP values plus a ranked top-N driver list.

Persistence
───────────
  The trained model bundle (XGBoost booster + feature list + metadata) is
  stored at MODEL_PATH as a joblib file.  It is loaded once at import time
  and refreshed in-memory after every retrain.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score

log = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "ml_model.joblib"
)

MIN_SAMPLES             = 20    # minimum rows to attempt training
DISTRESS_RETURN_THRESHOLD = -20.0  # % forward return below which = distress

FEATURE_COLS: List[str] = [
    # Balance-sheet health
    "debt_to_equity",
    "current_ratio",
    "icr",
    "fcf_margin",
    # Profitability
    "net_margin",
    "roa",
    "roe",
    "revenue_growth_yoy",
    # Valuation signals
    "pe_ratio",
    "ev_ebitda",
    # Scoring-model outputs (already normalised by their respective engines)
    "altman_z_score",
    "beneish_m_score",
    "risk_score",
    # Quality
    "quality_score",
]

# Singleton in-memory bundle: {"model", "feature_cols", "meta", "explainer"}
_bundle: Optional[dict] = None


# ── public API ────────────────────────────────────────────────────────────────

def get_model_status() -> dict:
    """Return whether a model is loaded, and its training metadata."""
    if _bundle is None:
        return {"loaded": False, "meta": None}
    return {"loaded": True, "meta": _bundle["meta"]}


def train(db) -> dict:
    """
    Build training data from `db`, fit an XGBoost classifier, compute
    cross-validated AUC, persist the bundle to disk, and refresh the
    in-memory singleton.

    Returns the training metadata dict (same as get_model_status()["meta"]).
    Raises ValueError if there is not enough labelled data.
    """
    X, y = _build_training_data(db)
    if len(X) < MIN_SAMPLES:
        raise ValueError(
            f"Not enough labelled samples to train ({len(X)} < {MIN_SAMPLES}). "
            "Analyse more companies or run the backtest harness first."
        )

    # Impute NaN with column medians
    medians = X.median()
    X_imp   = X.fillna(medians)

    clf = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        random_state=42,
        n_jobs=-1,
    )

    # Cross-validated AUC (stratified, 5-fold where possible)
    n_splits = min(5, int(y.sum()), int((y == 0).sum()))
    n_splits = max(2, n_splits)
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    cv_aucs = cross_val_score(clf, X_imp, y, cv=cv, scoring="roc_auc")
    cv_auc  = float(np.mean(cv_aucs))

    # Final model on all data
    clf.fit(X_imp, y)

    # Feature importance (gain-based, sorted)
    importance = dict(
        sorted(
            zip(FEATURE_COLS, clf.feature_importances_),
            key=lambda t: -t[1],
        )
    )

    meta = {
        "trained_at":     datetime.now(timezone.utc).isoformat(),
        "n_samples":      len(X),
        "n_distress":     int(y.sum()),
        "n_healthy":      int((y == 0).sum()),
        "cv_auc":         round(cv_auc, 4),
        "n_folds":        n_splits,
        "feature_importance": {k: round(float(v), 4) for k, v in importance.items()},
        "feature_cols":   FEATURE_COLS,
        "medians":        {c: (None if pd.isna(v) else round(float(v), 4))
                          for c, v in medians.items()},
    }

    explainer = shap.TreeExplainer(clf)

    bundle = {
        "model":        clf,
        "feature_cols": FEATURE_COLS,
        "medians":      medians,
        "meta":         meta,
        "explainer":    explainer,
    }

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(bundle, MODEL_PATH)
    log.info("ml_model: trained on %d samples, CV-AUC=%.4f", len(X), cv_auc)

    global _bundle
    _bundle = bundle
    return meta


def predict(ticker: str, db) -> dict:
    """
    Return distress probability + SHAP explanation for `ticker`.
    Raises ValueError if model not loaded or ticker not in DB.
    """
    if _bundle is None:
        raise ValueError("No ML model loaded. POST /ml/train first.")

    from backend.database.db import CompanyRecord          # lazy import
    rec = db.query(CompanyRecord).filter(CompanyRecord.ticker == ticker).first()
    if not rec:
        raise ValueError(f"Ticker {ticker} not found in database.")

    row = {col: getattr(rec, col, None) for col in FEATURE_COLS}
    X   = pd.DataFrame([row])[FEATURE_COLS]
    X_imp = X.fillna(_bundle["medians"])

    model    = _bundle["model"]
    expl     = _bundle["explainer"]

    prob = float(model.predict_proba(X_imp)[0, 1])

    # SHAP values for this single prediction
    shap_vals = expl.shap_values(X_imp)[0]          # shape (n_features,)
    shap_dict = {col: round(float(v), 4)
                 for col, v in zip(FEATURE_COLS, shap_vals)}

    # Rank drivers: positive SHAP = increases distress risk
    drivers = sorted(
        [
            {
                "feature":   col,
                "raw_value": row[col],
                "shap":      shap_dict[col],
                "direction": "increases_risk" if shap_dict[col] > 0 else "reduces_risk",
            }
            for col in FEATURE_COLS
        ],
        key=lambda d: -abs(d["shap"]),
    )

    if prob >= 0.60:
        label = "High Distress Risk"
    elif prob >= 0.35:
        label = "Moderate Distress Risk"
    else:
        label = "Low Distress Risk"

    return {
        "ticker":               ticker,
        "distress_probability": round(prob, 4),
        "distress_label":       label,
        "shap_values":          shap_dict,
        "top_drivers":          drivers[:5],
        "model_meta": {
            "trained_at": _bundle["meta"]["trained_at"],
            "cv_auc":     _bundle["meta"]["cv_auc"],
        },
    }


# ── startup loader ────────────────────────────────────────────────────────────

def load_model_from_disk() -> bool:
    """
    Attempt to load a previously persisted model bundle.
    Returns True if successful.  Called once at app startup.
    """
    global _bundle
    if not os.path.exists(MODEL_PATH):
        log.info("ml_model: no persisted model found at %s", MODEL_PATH)
        return False
    try:
        _bundle = joblib.load(MODEL_PATH)
        meta    = _bundle.get("meta", {})
        log.info(
            "ml_model: loaded — samples=%s  CV-AUC=%s  trained=%s",
            meta.get("n_samples"), meta.get("cv_auc"), meta.get("trained_at"),
        )
        return True
    except Exception as exc:
        log.warning("ml_model: failed to load from disk — %s", exc)
        _bundle = None
        return False


# ── training-data builder (private) ──────────────────────────────────────────

def _build_training_data(db) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Build (X, y) from the database.

    Strategy
    ────────
    1. Join BacktestObservation with CompanyRecord features; label = 1 if
       forward_return_pct < DISTRESS_RETURN_THRESHOLD.
    2. If fewer than MIN_SAMPLES scored observations exist, fall back to
       CompanyRecord rows with known Altman zone; label = 1 if zone == Distress.
    """
    from backend.database.db import BacktestObservation, CompanyRecord  # lazy

    # ── Strategy 1: backtested observations ──────────────────────────────────
    obs = (
        db.query(BacktestObservation)
        .filter(BacktestObservation.forward_return_pct.isnot(None))
        .all()
    )

    if len(obs) >= MIN_SAMPLES:
        tickers = list({o.ticker for o in obs})
        recs = {
            r.ticker: r
            for r in db.query(CompanyRecord)
            .filter(CompanyRecord.ticker.in_(tickers))
            .all()
        }
        rows, labels = [], []
        for o in obs:
            rec = recs.get(o.ticker)
            if rec is None:
                continue
            rows.append({col: getattr(rec, col, None) for col in FEATURE_COLS})
            labels.append(1 if o.forward_return_pct < DISTRESS_RETURN_THRESHOLD else 0)
        if len(rows) >= MIN_SAMPLES:
            log.info("ml_model: using %d backtest observations for training", len(rows))
            return pd.DataFrame(rows)[FEATURE_COLS], pd.Series(labels, dtype=int)

    # ── Strategy 2: Altman-derived labels ────────────────────────────────────
    companies = (
        db.query(CompanyRecord)
        .filter(CompanyRecord.altman_zone.isnot(None))
        .all()
    )
    rows, labels = [], []
    for rec in companies:
        rows.append({col: getattr(rec, col, None) for col in FEATURE_COLS})
        labels.append(1 if rec.altman_zone == "Distress" else 0)

    log.info(
        "ml_model: using %d CompanyRecord rows (Altman-derived labels)", len(rows)
    )
    return pd.DataFrame(rows)[FEATURE_COLS], pd.Series(labels, dtype=int)
