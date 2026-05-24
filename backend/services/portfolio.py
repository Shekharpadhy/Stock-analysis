"""
Portfolio analytics — aggregate a list of CompanyRecord rows into
portfolio-level metrics.

This module is the analytical bridge between the per-user watchlist (which
is just a set of tickers) and a meaningful "how is my book doing?" view.

Design
──────
The core function `summarise()` is pure: it accepts an iterable of records
and returns a dict.  No DB session, no I/O.  Callers (the API route) own
the loading of records via whatever join makes sense for the request.

Outputs
───────
  bcsi:               { mean, min, max, label_distribution{Strong|Fair|Watch|Weak} }
  risk:               { mean_risk_score, distribution{Low|Medium|High} }
  momentum:           { mean_momentum_score, distribution{Strong|Positive|Neutral|Negative|Weak} }
  sector_exposure:    { sector_name: count } (sorted by count desc)
  altman_zones:       { Safe|Grey|Distress|Unknown: count }
  highlights:         { strongest: [top 3 by bcsi], weakest: [bottom 3 by bcsi] }
  coverage:           int  (number of tickers in the portfolio)
  data_coverage_pct:  int  (% of tickers that have a BCSI score)
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ── small helpers ─────────────────────────────────────────────────────────────

def _bucket_risk(score: Optional[float]) -> str:
    if score is None: return "Unknown"
    if score >= 60:   return "High"
    if score >= 40:   return "Medium"
    return "Low"


def _safe_mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _record_summary(rec) -> Dict[str, Any]:
    """One-row projection for the highlights list."""
    return {
        "ticker":         rec.ticker,
        "name":           rec.name,
        "sector":         rec.sector,
        "bcsi_score":     rec.bcsi_score,
        "bcsi_label":     rec.bcsi_label,
        "risk_score":     rec.risk_score,
        "momentum_score": rec.momentum_score,
    }


# ── public API ────────────────────────────────────────────────────────────────

def summarise(records: Iterable[Any]) -> Dict[str, Any]:
    """
    Aggregate `records` (any object with the CompanyRecord-shaped attributes)
    into a portfolio summary.  Returns an empty-shape dict when the iterable
    is empty so the caller never has to special-case it.
    """
    records: List[Any] = list(records)
    if not records:
        return {
            "coverage":          0,
            "data_coverage_pct": 0,
            "bcsi":              _empty_bcsi(),
            "risk":              _empty_risk(),
            "momentum":          _empty_momentum(),
            "sector_exposure":   {},
            "altman_zones":      {},
            "highlights":        {"strongest": [], "weakest": []},
        }

    bcsi_scores     = [r.bcsi_score     for r in records if r.bcsi_score     is not None]
    risk_scores     = [r.risk_score     for r in records if r.risk_score     is not None]
    momentum_scores = [r.momentum_score for r in records if r.momentum_score is not None]

    bcsi_labels = Counter(r.bcsi_label or "Unknown" for r in records)
    altman      = Counter(r.altman_zone or "Unknown" for r in records)
    momentum_lb = Counter(r.momentum_label or "Unknown" for r in records)
    risk_dist   = Counter(_bucket_risk(r.risk_score) for r in records)
    sectors     = Counter(r.sector or "Unknown" for r in records)

    # Highlights — sort by BCSI desc/asc, ignoring NULLs (a ticker with no
    # score isn't meaningfully "strongest" or "weakest").
    scored = [r for r in records if r.bcsi_score is not None]
    scored_sorted = sorted(scored, key=lambda r: r.bcsi_score, reverse=True)
    strongest = [_record_summary(r) for r in scored_sorted[:3]]
    weakest   = [_record_summary(r) for r in scored_sorted[-3:][::-1]]

    coverage = len(records)
    data_coverage_pct = round(len(bcsi_scores) / coverage * 100) if coverage else 0

    return {
        "coverage":          coverage,
        "data_coverage_pct": data_coverage_pct,
        "bcsi": {
            "mean":               _safe_mean(bcsi_scores),
            "min":                min(bcsi_scores) if bcsi_scores else None,
            "max":                max(bcsi_scores) if bcsi_scores else None,
            "label_distribution": dict(bcsi_labels),
        },
        "risk": {
            "mean_risk_score": _safe_mean(risk_scores),
            "distribution":    dict(risk_dist),
        },
        "momentum": {
            "mean_momentum_score": _safe_mean(momentum_scores),
            "distribution":        dict(momentum_lb),
        },
        # Sort exposures by descending count so the UI can render top-N.
        "sector_exposure":   dict(sectors.most_common()),
        "altman_zones":      dict(altman),
        "highlights": {
            "strongest": strongest,
            "weakest":   weakest,
        },
    }


# ── empty-shape helpers (keep the response shape stable across coverage) ─────

def _empty_bcsi() -> Dict[str, Any]:
    return {"mean": None, "min": None, "max": None, "label_distribution": {}}


def _empty_risk() -> Dict[str, Any]:
    return {"mean_risk_score": None, "distribution": {}}


def _empty_momentum() -> Dict[str, Any]:
    return {"mean_momentum_score": None, "distribution": {}}
