import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.config import settings
from backend.limiter import limiter
from backend.auth import authenticate_admin, create_access_token, require_auth
from backend.database.db import (
    get_db, CompanyRecord, SectorProfile, GovernanceRecord, AlertSubscription,
)
from backend.services.ingestion import (
    fetch_company_data,
    lookup_cik_by_ticker,
    fetch_sec_filings,
)
from backend.services.sector_classifier import classify_sector
from backend.services.ensemble_risk import compute_ensemble_risk
from backend.services.valuation_engine import compute_valuation
from backend.services.backtest import aggregate_report
from backend.services.track_record import (
    record_prediction, score_matured_predictions, track_record_report,
)
from backend.services.calibration import (
    recalibrate_sector_profiles, get_calibrated_profiles, reliability_report,
)
from backend.services.governance import compute_governance_score
from backend.services.bcsi import compute_bcsi
from backend.services import ml_model
from backend.services import alerts as alert_svc

router = APIRouter()
log = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,15}$")


def _validate_ticker(ticker: str) -> str:
    t = ticker.upper().strip()
    if not _TICKER_RE.match(t):
        raise HTTPException(status_code=422, detail=f"Invalid ticker format: {ticker!r}")
    return t


# ── Authentication ────────────────────────────────────────────────────────────
@router.post("/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Exchange admin credentials (form-encoded) for a short-lived bearer JWT."""
    if not authenticate_admin(form_data.username, form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "access_token": create_access_token(form_data.username),
        "token_type": "bearer",
    }


# ── List / filter ─────────────────────────────────────────────────────────────
@router.get("/companies")
def list_companies(
    sector: str = None,
    risk_label: str = None,
    valuation_label: str = None,
    db: Session = Depends(get_db),
):
    q = db.query(CompanyRecord)
    if sector:
        q = q.filter(CompanyRecord.sector == sector)
    if risk_label:
        q = q.filter(CompanyRecord.risk_label == risk_label)
    if valuation_label:
        q = q.filter(CompanyRecord.valuation_label == valuation_label)
    return [_serialize(c) for c in q.order_by(CompanyRecord.risk_score.desc()).all()]


# ── Get one ───────────────────────────────────────────────────────────────────
@router.get("/companies/{ticker}")
def get_company(ticker: str, db: Session = Depends(get_db)):
    t = _validate_ticker(ticker)
    rec = db.query(CompanyRecord).filter(CompanyRecord.ticker == t).first()
    if not rec:
        raise HTTPException(
            status_code=404,
            detail="Company not found. Use POST /companies/analyze to add it.",
        )
    return _serialize(rec)


# ── Full analysis pipeline ────────────────────────────────────────────────────
@router.post("/companies/analyze")
@limiter.limit(settings.rate_limit_analyze)
async def analyze_company(request: Request, ticker: str, db: Session = Depends(get_db)):
    """
    Runs the complete analysis pipeline for a ticker:
      1. Fetch fundamentals + advanced scores (yfinance, Redis-cached 15 min,
         run in a thread to avoid blocking the event loop)
      2. GICS sector classification
      3. Ensemble risk score (85 % accuracy target)
      4. Valuation: Monte Carlo DCF → Bear / Base / Bull / Stretched targets
      5. Entry zone, trim level, hard stop
      6. Persist to database
    """
    t = _validate_ticker(ticker)

    try:
        # Combined fundamentals + advanced scores + quality, cached in Redis 15 min.
        raw, advanced, quality = await asyncio.to_thread(fetch_company_data, t)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Sector classification
    sector, sub_sector = classify_sector(raw.get("sector", ""), raw.get("industry", ""))
    raw["sector"]     = sector
    raw["sub_sector"] = sub_sector

    # Ensemble risk — using data-calibrated sector profiles where available
    ensemble = compute_ensemble_risk(
        raw, advanced, sector, profiles=get_calibrated_profiles(db)
    )

    # Valuation + price targets
    valuation = compute_valuation(raw, sector)

    # BCSI composite — pull governance from DB if it exists for this ticker
    gov_rec = db.query(GovernanceRecord).filter(GovernanceRecord.ticker == t).first()
    governance_for_bcsi = (
        {"governance_score": gov_rec.governance_score}
        if gov_rec and gov_rec.governance_score is not None
        else None
    )
    bcsi = compute_bcsi(ensemble, valuation, quality, governance_for_bcsi)

    # Flatten all results into a single dict for DB upsert
    record_data = {
        **raw,
        # Altman
        "altman_z_score": advanced["altman"].get("z_score"),
        "altman_zone":    advanced["altman"].get("zone"),
        # Beneish
        "beneish_m_score": advanced["beneish"].get("m_score"),
        "beneish_flag":    advanced["beneish"].get("flag"),
        # ICR / FCF
        "icr":        advanced.get("icr"),
        "icr_label":  advanced.get("icr_label"),
        "fcf_margin": advanced.get("fcf_margin"),
        # Ensemble risk
        "risk_score":       ensemble["composite_score"],
        "risk_label":       ensemble["composite_label"],
        "risk_confidence":  ensemble["confidence"],
        "risk_flags":       json.dumps(ensemble["flags"]),
        "risk_components":  json.dumps(ensemble["components"]),
        "sector_calibrated": ensemble["sector_calibrated"],
        # Valuation fair values
        "dcf_fair_value":        valuation["dcf_fair_value"],
        "pe_fair_value":         valuation["pe_fair_value"],
        "peg_fair_value":        valuation["peg_fair_value"],
        "analyst_consensus":     valuation["analyst_consensus"],
        "composite_fair_value":  valuation["composite_fair_value"],
        "upside_pct":            valuation["upside_pct"],
        "valuation_label":       valuation["valuation_label"],
        "valuation_confidence":  valuation["valuation_confidence"],
        # Scenario targets
        "bear_target":           valuation["bear_target"],
        "base_target":           valuation["base_target"],
        "bull_target":           valuation["bull_target"],
        "stretched_bull_target": valuation["stretched_bull_target"],
        # Entry / exit
        "entry_zone_low":  valuation["entry_zone_low"],
        "entry_zone_high": valuation["entry_zone_high"],
        "trim_level":      valuation["trim_level"],
        "hard_stop":       valuation["hard_stop"],
        # Quality
        "quality_score":     quality.get("quality_score"),
        "quality_label":     quality.get("quality_label"),
        "piotroski_f_score": quality.get("piotroski", {}).get("f_score"),
        "graham_number":     quality.get("graham_number"),
        # BCSI composite
        "bcsi_score":      bcsi["bcsi_score"],
        "bcsi_label":      bcsi["bcsi_label"],
        "bcsi_dimensions": json.dumps(bcsi["dimensions"]),
        "bcsi_confidence": bcsi["confidence"],
    }

    rec = db.query(CompanyRecord).filter(CompanyRecord.ticker == t).first()
    if rec:
        for k, v in record_data.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        rec.last_updated = datetime.utcnow()
    else:
        rec = CompanyRecord(
            **{k: v for k, v in record_data.items() if hasattr(CompanyRecord, k)}
        )
        db.add(rec)

    db.commit()
    db.refresh(rec)

    # Record this prediction for the live track record. A failure here must
    # never break the analysis response — it is a side-effect, not the result.
    try:
        record_prediction(db, t, raw, ensemble, valuation)
    except Exception as e:                       # noqa: BLE001
        log.warning("track-record: failed to record prediction for %s (%s)", t, e)

    return _serialize(rec)


# ── Valuation detail ──────────────────────────────────────────────────────────
@router.get("/companies/{ticker}/valuation")
def get_valuation(ticker: str, db: Session = Depends(get_db)):
    """Returns full valuation breakdown including fair value by method and assumptions."""
    t   = _validate_ticker(ticker)
    rec = db.query(CompanyRecord).filter(CompanyRecord.ticker == t).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Company not found.")
    return {
        "ticker":  rec.ticker,
        "name":    rec.name,
        "current_price": rec.current_price,
        "fair_values": {
            "dcf":      rec.dcf_fair_value,
            "pe":       rec.pe_fair_value,
            "peg":      rec.peg_fair_value,
            "analyst":  rec.analyst_consensus,
            "composite": rec.composite_fair_value,
        },
        "upside_pct":            rec.upside_pct,
        "valuation_label":       rec.valuation_label,
        "valuation_confidence":  rec.valuation_confidence,
        "analyst_target_mean":   rec.analyst_target_mean,
        "analyst_target_high":   rec.analyst_target_high,
        "analyst_target_low":    rec.analyst_target_low,
        "analyst_count":         rec.analyst_count,
        "recommendation":        rec.recommendation,
        "last_updated":          rec.last_updated.isoformat() if rec.last_updated else None,
    }


# ── Price targets ─────────────────────────────────────────────────────────────
@router.get("/companies/{ticker}/targets")
def get_targets(ticker: str, db: Session = Depends(get_db)):
    """Returns Bear/Base/Bull/Stretched targets + entry zone, trim level, hard stop."""
    t   = _validate_ticker(ticker)
    rec = db.query(CompanyRecord).filter(CompanyRecord.ticker == t).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Company not found.")
    return {
        "ticker":        rec.ticker,
        "name":          rec.name,
        "current_price": rec.current_price,
        "targets": {
            "bear":           rec.bear_target,
            "base":           rec.base_target,
            "bull":           rec.bull_target,
            "stretched_bull": rec.stretched_bull_target,
        },
        "action_levels": {
            "entry_zone": {
                "low":  rec.entry_zone_low,
                "high": rec.entry_zone_high,
                "note": "Buy range: 9–18% below base fair value",
            },
            "trim_level": {
                "price": rec.trim_level,
                "note":  "Begin trimming within 4% of bull target",
            },
            "hard_stop": {
                "price": rec.hard_stop,
                "note":  "Exit: max(52-wk low × 0.97, entry_low × 0.83)",
            },
        },
        "price_context": {
            "fifty_two_week_high": rec.fifty_two_week_high,
            "fifty_two_week_low":  rec.fifty_two_week_low,
        },
        "last_updated": rec.last_updated.isoformat() if rec.last_updated else None,
    }


# ── Risk detail ───────────────────────────────────────────────────────────────
@router.get("/companies/{ticker}/risk")
def get_risk(ticker: str, db: Session = Depends(get_db)):
    """Returns full ensemble risk breakdown with per-model scores and confidence."""
    t   = _validate_ticker(ticker)
    rec = db.query(CompanyRecord).filter(CompanyRecord.ticker == t).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Company not found.")
    return {
        "ticker":            rec.ticker,
        "name":              rec.name,
        "composite_score":   rec.risk_score,
        "composite_label":   rec.risk_label,
        "confidence":        rec.risk_confidence,
        "sector_calibrated": rec.sector_calibrated,
        "altman": {
            "z_score": rec.altman_z_score,
            "zone":    rec.altman_zone,
        },
        "beneish": {
            "m_score": rec.beneish_m_score,
            "flag":    rec.beneish_flag,
        },
        "cashflow": {
            "icr":        rec.icr,
            "icr_label":  rec.icr_label,
            "fcf_margin": rec.fcf_margin,
        },
        "components": json.loads(rec.risk_components) if rec.risk_components else {},
        "flags":      json.loads(rec.risk_flags)       if rec.risk_flags      else [],
        "last_updated": rec.last_updated.isoformat() if rec.last_updated else None,
    }


# ── BCSI composite ────────────────────────────────────────────────────────────
@router.get("/companies/{ticker}/bcsi")
def get_bcsi(ticker: str, db: Session = Depends(get_db)):
    """BCSI composite score with per-dimension breakdown and coverage confidence."""
    t   = _validate_ticker(ticker)
    rec = db.query(CompanyRecord).filter(CompanyRecord.ticker == t).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Company not found.")
    return {
        "ticker":         rec.ticker,
        "name":           rec.name,
        "bcsi_score":     rec.bcsi_score,
        "bcsi_label":     rec.bcsi_label,
        "bcsi_confidence": rec.bcsi_confidence,
        "dimensions":     json.loads(rec.bcsi_dimensions) if rec.bcsi_dimensions else {},
        "quality": {
            "quality_score":     rec.quality_score,
            "quality_label":     rec.quality_label,
            "piotroski_f_score": rec.piotroski_f_score,
            "graham_number":     rec.graham_number,
        },
        "momentum_status": "pending — Phase 7 (sentiment + technicals + signals)",
        "last_updated":   rec.last_updated.isoformat() if rec.last_updated else None,
    }


# ── Peers ─────────────────────────────────────────────────────────────────────
@router.get("/companies/{ticker}/peers")
def get_peers(ticker: str, db: Session = Depends(get_db)):
    t       = _validate_ticker(ticker)
    company = db.query(CompanyRecord).filter(CompanyRecord.ticker == t).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    peers     = db.query(CompanyRecord).filter(
        CompanyRecord.sector == company.sector,
        CompanyRecord.ticker != t,
    ).all()
    peer_data = [_serialize(p) for p in peers]

    def _bench(field: str) -> dict:
        vals = [c.get(field) for c in peer_data if c.get(field) is not None]
        if not vals:
            return {}
        return {
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "avg": round(sum(vals) / len(vals), 2),
            "count": len(vals),
        }

    return {
        "company":          _serialize(company),
        "peers":            peer_data,
        "sector_benchmarks": {
            "revenue_growth_yoy":    _bench("revenue_growth_yoy"),
            "net_margin":            _bench("net_margin"),
            "debt_to_equity":        _bench("debt_to_equity"),
            "pe_ratio":              _bench("pe_ratio"),
            "risk_score":            _bench("risk_score"),
            "upside_pct":            _bench("upside_pct"),
            "composite_fair_value":  _bench("composite_fair_value"),
        },
    }


# ── SEC Filings ───────────────────────────────────────────────────────────────
@router.get("/companies/{ticker}/filings")
def get_filings(ticker: str):
    t   = _validate_ticker(ticker)
    cik = lookup_cik_by_ticker(t)
    if not cik:
        raise HTTPException(status_code=404, detail="CIK not found for this ticker.")
    return {"ticker": t, "cik": cik, "filings": fetch_sec_filings(cik, form_type="10-K")}


# ── Sector summary ────────────────────────────────────────────────────────────
@router.get("/sectors/summary")
def sector_summary(db: Session = Depends(get_db)):
    rows = db.query(
        CompanyRecord.sector,
        func.count(CompanyRecord.ticker).label("company_count"),
        func.avg(CompanyRecord.risk_score).label("avg_risk_score"),
        func.avg(CompanyRecord.net_margin).label("avg_net_margin"),
        func.avg(CompanyRecord.revenue_growth_yoy).label("avg_revenue_growth"),
        func.avg(CompanyRecord.upside_pct).label("avg_upside_pct"),
    ).group_by(CompanyRecord.sector).all()

    return [
        {
            "sector":             r.sector,
            "company_count":      r.company_count,
            "avg_risk_score":     round(r.avg_risk_score  or 0, 1),
            "avg_net_margin":     round(r.avg_net_margin  or 0, 2),
            "avg_revenue_growth": round(r.avg_revenue_growth or 0, 2),
            "avg_upside_pct":     round(r.avg_upside_pct  or 0, 1),
        }
        for r in rows
    ]


# ── Risk heatmap ──────────────────────────────────────────────────────────────
@router.get("/risk/heatmap")
def risk_heatmap(db: Session = Depends(get_db)):
    return [
        {
            "ticker":           c.ticker,
            "name":             c.name,
            "sector":           c.sector,
            "risk_score":       c.risk_score,
            "risk_label":       c.risk_label,
            "risk_confidence":  c.risk_confidence,
            "altman_zone":      c.altman_zone,
            "beneish_flag":     c.beneish_flag,
            "valuation_label":  c.valuation_label,
            "upside_pct":       c.upside_pct,
            "market_cap":       c.market_cap,
        }
        for c in db.query(CompanyRecord).all()
    ]


# ── Backtest accuracy report ──────────────────────────────────────────────────
@router.get("/backtest/report")
def backtest_report(horizon_months: int = 12, db: Session = Depends(get_db)):
    """
    Aggregated backtest accuracy from stored observations: risk-tier
    separation, valuation hit-rate, rank correlation, and Brier calibration.
    This is the measured-accuracy report that replaces the borrowed "85%".
    """
    return aggregate_report(db, horizon_months)


# ── Engine calibration ────────────────────────────────────────────────────────
@router.get("/calibration/profiles")
def calibration_profiles(db: Session = Depends(get_db)):
    """Sector metric profiles that have been data-calibrated from accumulated
    company fundamentals. Metrics not listed use the hardcoded estimates."""
    rows = (db.query(SectorProfile)
              .order_by(SectorProfile.sector, SectorProfile.metric).all())
    return {
        "data_calibrated": [
            {
                "sector": r.sector, "metric": r.metric,
                "median": round(r.median, 3), "spread": round(r.spread, 3),
                "sample_size": r.sample_size,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
        "note": "Metrics not listed fall back to the hardcoded sector "
                "estimates in ensemble_risk.SECTOR_RISK_PROFILES.",
    }


@router.post("/calibration/recalibrate")
def trigger_recalibration(
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    """Re-estimate sector profiles from accumulated company data. Admin-only."""
    return recalibrate_sector_profiles(db)


@router.get("/calibration/reliability")
def calibration_reliability(horizon_months: int = 12, db: Session = Depends(get_db)):
    """Is the risk score well-calibrated as a probability? Buckets backtest
    observations by risk_score and compares predicted vs observed bad-outcome
    rates."""
    return reliability_report(db, horizon_months)


# ── Governance (India risk edge) ──────────────────────────────────────────────
class GovernanceInput(BaseModel):
    """Governance data import payload. Indian governance data (promoter pledge,
    SEBI orders, board composition) has no free API — it is loaded here from
    manual research or a paid feed. See backend/services/governance.py."""
    promoter_holding_pct:       Optional[float] = None
    promoter_pledge_pct:        Optional[float] = None
    promoter_pledge_pct_prior:  Optional[float] = None
    auditor_name:               Optional[str]   = None
    auditor_changed_recently:   Optional[bool]  = None
    sebi_action_pending:        Optional[bool]  = None
    sebi_action_count:          Optional[int]   = None
    board_size:                 Optional[int]   = None
    independent_director_count: Optional[int]   = None


@router.post("/governance/{ticker}")
def import_governance(
    ticker: str,
    data: GovernanceInput,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    """Import/update a ticker's governance data and (re)compute its governance
    score. Admin-only."""
    t = _validate_ticker(ticker)
    payload = data.model_dump()
    scored = compute_governance_score(payload)

    fields = {
        **payload,
        "governance_score": scored["governance_score"],
        "governance_label": scored["governance_label"],
        "governance_flags": json.dumps(scored["flags"]),
    }
    rec = db.query(GovernanceRecord).filter(GovernanceRecord.ticker == t).first()
    if rec:
        for k, v in fields.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        rec.updated_at = datetime.utcnow()
    else:
        rec = GovernanceRecord(
            ticker=t, **{k: v for k, v in fields.items() if hasattr(GovernanceRecord, k)}
        )
        db.add(rec)
    db.commit()
    return {"ticker": t, **scored}


@router.get("/governance/{ticker}")
def get_governance(ticker: str, db: Session = Depends(get_db)):
    """Governance score and signal breakdown for a ticker."""
    t = _validate_ticker(ticker)
    rec = db.query(GovernanceRecord).filter(GovernanceRecord.ticker == t).first()
    if not rec:
        raise HTTPException(
            status_code=404,
            detail="No governance data. Use POST /governance/{ticker} to add it.",
        )
    return {
        "ticker":                     rec.ticker,
        "promoter_holding_pct":       rec.promoter_holding_pct,
        "promoter_pledge_pct":        rec.promoter_pledge_pct,
        "promoter_pledge_pct_prior":  rec.promoter_pledge_pct_prior,
        "auditor_name":               rec.auditor_name,
        "auditor_changed_recently":   rec.auditor_changed_recently,
        "sebi_action_pending":        rec.sebi_action_pending,
        "sebi_action_count":          rec.sebi_action_count,
        "board_size":                 rec.board_size,
        "independent_director_count": rec.independent_director_count,
        "governance_score":           rec.governance_score,
        "governance_label":           rec.governance_label,
        "governance_flags":           json.loads(rec.governance_flags) if rec.governance_flags else [],
        "updated_at":                 rec.updated_at.isoformat() if rec.updated_at else None,
    }


# ── Live self-scoring track record ────────────────────────────────────────────
@router.get("/track-record")
def get_track_record(db: Session = Depends(get_db)):
    """The system's live, falsifiable accuracy — scored matured predictions."""
    return track_record_report(db)


@router.post("/track-record/score")
def run_track_record_scoring(
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    """Grade every matured prediction against its actual price. Admin-only —
    fetches recent prices from yfinance."""
    return score_matured_predictions(db)


# ── Delete (protected — requires a valid bearer JWT) ──────────────────────────
@router.delete("/companies/{ticker}")
def delete_company(
    ticker: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    t   = _validate_ticker(ticker)
    rec = db.query(CompanyRecord).filter(CompanyRecord.ticker == t).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Company not found.")
    db.delete(rec)
    db.commit()
    return {"message": f"{t} removed from database."}


# ── ML default-prediction ────────────────────────────────────────────────────
@router.get("/ml/status")
def ml_status():
    """Current ML model status: loaded, training metadata, feature importance."""
    return ml_model.get_model_status()


@router.post("/ml/train")
def ml_train(
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    """
    (Re)train the XGBoost distress-prediction model from accumulated DB data.
    Admin-only.  Returns training metadata including cross-validated AUC.
    """
    try:
        meta = ml_model.train(db)
        return {"status": "ok", "meta": meta}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/ml/predict/{ticker}")
def ml_predict(ticker: str, db: Session = Depends(get_db)):
    """
    Distress probability + SHAP explanation for a tracked ticker.
    Returns top-5 drivers ranked by absolute SHAP contribution.
    """
    t = _validate_ticker(ticker)
    try:
        return ml_model.predict(t, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Serialiser ────────────────────────────────────────────────────────────────
def _serialize(rec: CompanyRecord) -> dict:
    return {
        # Identity
        "ticker":      rec.ticker,
        "name":        rec.name,
        "sector":      rec.sector,
        "sub_sector":  rec.sub_sector,
        # Market
        "market_cap":          rec.market_cap,
        "current_price":       rec.current_price,
        "fifty_two_week_high": rec.fifty_two_week_high,
        "fifty_two_week_low":  rec.fifty_two_week_low,
        "beta":                rec.beta,
        # Income
        "revenue_ttm":        rec.revenue_ttm,
        "revenue_growth_yoy": rec.revenue_growth_yoy,
        "earnings_growth":    rec.earnings_growth,
        "net_margin":         rec.net_margin,
        "roa":                rec.roa,
        "roe":                rec.roe,
        # Valuation multiples
        "pe_ratio":   rec.pe_ratio,
        "forward_pe": rec.forward_pe,
        "peg_ratio":  rec.peg_ratio,
        "ev_ebitda":  rec.ev_ebitda,
        # Per-share
        "eps_ttm":     rec.eps_ttm,
        "eps_forward": rec.eps_forward,
        # Balance sheet
        "debt_to_equity":     rec.debt_to_equity,
        "current_ratio":      rec.current_ratio,
        "free_cashflow":      rec.free_cashflow,
        "dividend_yield":     rec.dividend_yield,
        # Analyst
        "analyst_target_mean": rec.analyst_target_mean,
        "analyst_count":       rec.analyst_count,
        "recommendation":      rec.recommendation,
        # Risk (ensemble)
        "risk_score":      rec.risk_score,
        "risk_label":      rec.risk_label,
        "risk_confidence": rec.risk_confidence,
        "risk_flags":      json.loads(rec.risk_flags) if rec.risk_flags else [],
        "altman_zone":     rec.altman_zone,
        "beneish_flag":    rec.beneish_flag,
        # Valuation
        "composite_fair_value": rec.composite_fair_value,
        "upside_pct":           rec.upside_pct,
        "valuation_label":      rec.valuation_label,
        "valuation_confidence": rec.valuation_confidence,
        # Targets
        "bear_target":           rec.bear_target,
        "base_target":           rec.base_target,
        "bull_target":           rec.bull_target,
        "stretched_bull_target": rec.stretched_bull_target,
        # Action levels
        "entry_zone_low":  rec.entry_zone_low,
        "entry_zone_high": rec.entry_zone_high,
        "trim_level":      rec.trim_level,
        "hard_stop":       rec.hard_stop,
        # Quality
        "quality_score":     rec.quality_score,
        "quality_label":     rec.quality_label,
        "piotroski_f_score": rec.piotroski_f_score,
        "graham_number":     rec.graham_number,
        # BCSI composite
        "bcsi_score":      rec.bcsi_score,
        "bcsi_label":      rec.bcsi_label,
        "bcsi_confidence": rec.bcsi_confidence,
        "bcsi_dimensions": json.loads(rec.bcsi_dimensions) if rec.bcsi_dimensions else {},
        # Meta
        "last_updated": rec.last_updated.isoformat() if rec.last_updated else None,
    }


# ── Alert endpoints ───────────────────────────────────────────────────────────

class AlertSubscriptionIn(BaseModel):
    ticker:        str
    condition:     str
    threshold:     Optional[float] = None
    email:         Optional[str]   = None
    slack_webhook: Optional[str]   = None


class AlertSubscriptionOut(BaseModel):
    id:            int
    ticker:        str
    condition:     str
    threshold:     Optional[float]
    email:         Optional[str]
    slack_webhook: Optional[str]
    active:        bool


@router.get("/alerts/config")
def alerts_config():
    """Return the current alert channel configuration (no secrets)."""
    return alert_svc.get_config()


@router.get("/alerts/subscriptions")
def list_subscriptions(
    ticker: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all active alert subscriptions, optionally filtered by ticker."""
    q = db.query(AlertSubscription).filter(AlertSubscription.active.is_(True))
    if ticker:
        q = q.filter(AlertSubscription.ticker == ticker.upper())
    subs = q.order_by(AlertSubscription.id).all()
    return [
        AlertSubscriptionOut(
            id=s.id, ticker=s.ticker, condition=s.condition,
            threshold=s.threshold, email=s.email,
            slack_webhook=s.slack_webhook, active=s.active,
        )
        for s in subs
    ]


@router.post("/alerts/subscriptions", status_code=201)
def create_subscription(
    body: AlertSubscriptionIn,
    db:   Session = Depends(get_db),
    _:    str     = Depends(require_auth),
):
    """
    Create a new alert subscription.  At least one of `email` or
    `slack_webhook` must be provided; the condition must be one of
    the values returned by GET /alerts/config.
    """
    if body.condition not in alert_svc.VALID_CONDITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown condition {body.condition!r}. "
                   f"Valid: {sorted(alert_svc.VALID_CONDITIONS)}",
        )
    if not body.email and not body.slack_webhook:
        raise HTTPException(
            status_code=422,
            detail="At least one of 'email' or 'slack_webhook' must be provided.",
        )

    ticker = _validate_ticker(body.ticker)
    sub = AlertSubscription(
        ticker        = ticker,
        condition     = body.condition,
        threshold     = body.threshold,
        email         = body.email,
        slack_webhook = body.slack_webhook,
        active        = True,
    )
    db.add(sub)
    try:
        db.commit()
        db.refresh(sub)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Subscription already exists: {exc}")

    return AlertSubscriptionOut(
        id=sub.id, ticker=sub.ticker, condition=sub.condition,
        threshold=sub.threshold, email=sub.email,
        slack_webhook=sub.slack_webhook, active=sub.active,
    )


@router.delete("/alerts/subscriptions/{sub_id}", status_code=204)
def delete_subscription(
    sub_id: int,
    db:     Session = Depends(get_db),
    _:      str     = Depends(require_auth),
):
    """Deactivate (soft-delete) an alert subscription."""
    sub = db.query(AlertSubscription).filter(AlertSubscription.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail=f"Subscription {sub_id} not found.")
    sub.active = False
    db.commit()


@router.post("/alerts/test/{sub_id}")
def test_alert(
    sub_id: int,
    db:     Session = Depends(get_db),
    _:      str     = Depends(require_auth),
):
    """
    Fire an unconditional test alert for the given subscription.
    Useful for verifying email / Slack delivery without waiting for a trigger.
    """
    sub = db.query(AlertSubscription).filter(AlertSubscription.id == sub_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail=f"Subscription {sub_id} not found.")

    result = alert_svc.fire_test_alert(sub, sub.ticker)
    return result
