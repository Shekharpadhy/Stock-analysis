"""
BCSI composite score — the single number the platform is built around.

Blends the engine outputs into one 0–100 score (higher = better) across five
dimensions. Each dimension is normalised so higher is always better:

  Risk        25%   100 - ensemble risk score
  Quality     25%   Piotroski-driven quality score
  Valuation   20%   upside vs current price, centred at 50
  Momentum    15%   PENDING — added in Phase 7 (sentiment + technicals + signals)
  Governance  15%   100 - governance risk score

Weights renormalise over whichever dimensions have data, so the score is
honest about coverage — Momentum is always absent for now, and Governance is
present only once governance data has been imported for the ticker.
"""

from typing import Optional


_WEIGHTS = {
    "risk": 0.25, "quality": 0.25, "valuation": 0.20,
    "momentum": 0.15, "governance": 0.15,
}


def _valuation_dimension(upside_pct: Optional[float]) -> Optional[float]:
    """Map upside-to-fair-value into a 0–100 dimension centred at 50 (fair)."""
    if upside_pct is None:
        return None
    return round(max(0.0, min(100.0, 50.0 + upside_pct)), 1)


def compute_bcsi(
    ensemble: dict,
    valuation: dict,
    quality: dict,
    governance: Optional[dict] = None,
) -> dict:
    """
    Compose the BCSI score from the engine outputs. `governance` is optional —
    pass {"governance_score": ...} when governance data exists, else None.
    """
    dims: dict[str, dict] = {}

    # Risk — invert the risk score so higher = safer = better.
    risk_score = ensemble.get("composite_score")
    if risk_score is not None:
        dims["risk"] = {"score": round(100.0 - risk_score, 1),
                        "weight": _WEIGHTS["risk"]}

    # Quality — already higher = better.
    q = quality.get("quality_score") if quality else None
    if q is not None:
        dims["quality"] = {"score": q, "weight": _WEIGHTS["quality"]}

    # Valuation — upside vs fair value.
    val_dim = _valuation_dimension(valuation.get("upside_pct"))
    if val_dim is not None:
        dims["valuation"] = {"score": val_dim, "weight": _WEIGHTS["valuation"]}

    # Governance — invert the governance risk score.
    if governance and governance.get("governance_score") is not None:
        dims["governance"] = {
            "score": round(100.0 - governance["governance_score"], 1),
            "weight": _WEIGHTS["governance"],
        }

    # Momentum — deliberately absent until Phase 7.

    if not dims:
        return {
            "bcsi_score": None, "bcsi_label": "Unknown", "dimensions": {},
            "momentum_status": "pending — Phase 7 (sentiment + technicals + signals)",
            "confidence": 0,
        }

    total_w = sum(d["weight"] for d in dims.values())
    bcsi = round(
        sum(d["score"] * (d["weight"] / total_w) for d in dims.values()), 1
    )

    if bcsi >= 70:
        label = "Strong"
    elif bcsi >= 55:
        label = "Fair"
    elif bcsi >= 40:
        label = "Watch"
    else:
        label = "Weak"

    return {
        "bcsi_score": bcsi,
        "bcsi_label": label,
        "dimensions": {
            name: {"score": d["score"], "weight": round(d["weight"] / total_w, 3)}
            for name, d in dims.items()
        },
        "momentum_status": "pending — Phase 7 (sentiment + technicals + signals)",
        # 5 dimensions total; Momentum is always missing today, so 4/5 is the
        # current ceiling — the score states its own coverage honestly.
        "confidence": round(len(dims) / len(_WEIGHTS) * 100),
    }
