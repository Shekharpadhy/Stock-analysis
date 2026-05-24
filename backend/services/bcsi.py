"""
BCSI composite score — the single number the platform is built around.

Blends the engine outputs into one 0–100 score (higher = better) across five
dimensions. Each dimension is normalised so higher is always better:

  Risk        25%   100 - ensemble risk score
  Quality     25%   Piotroski-driven quality score
  Valuation   20%   upside vs current price, centred at 50
  Momentum    15%   price returns + 52-week position + volume + analyst
  Governance  15%   100 - governance risk score

Weights renormalise over whichever dimensions have data, so the score is
honest about coverage — Momentum may be absent for a ticker with no price
history yet, Governance is present only after governance data is imported.
"""

from typing import Optional, Dict, Any


_WEIGHTS: Dict[str, float] = {
    "risk":       0.25,
    "quality":    0.25,
    "valuation":  0.20,
    "momentum":   0.15,
    "governance": 0.15,
}


def _valuation_dimension(upside_pct: Optional[float]) -> Optional[float]:
    """Map upside-to-fair-value into a 0–100 dimension centred at 50 (fair)."""
    if upside_pct is None:
        return None
    return round(max(0.0, min(100.0, 50.0 + upside_pct)), 1)


def _label_for(score: float) -> str:
    if score >= 70: return "Strong"
    if score >= 55: return "Fair"
    if score >= 40: return "Watch"
    return "Weak"


def compute_bcsi(
    ensemble: Dict[str, Any],
    valuation: Dict[str, Any],
    quality: Optional[Dict[str, Any]],
    governance: Optional[Dict[str, Any]] = None,
    momentum: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compose the BCSI score from the engine outputs.  Each input is expected
    to be the dict shape produced by its corresponding engine:

      ensemble    {"composite_score": float|None, ...}
      valuation   {"upside_pct":      float|None, ...}
      quality     {"quality_score":   float|None, ...}
      governance  {"governance_score": float|None, ...}        (optional)
      momentum    {"momentum_score":  float|None, ...}         (optional)

    Returns a dimensions dict with per-dimension {score, weight} (weights
    renormalised over present dimensions) plus the headline `bcsi_score`,
    `bcsi_label`, and `confidence` (% of dimensions with data).
    """
    dims: Dict[str, Dict[str, float]] = {}

    # Risk — invert the risk score so higher = safer = better.
    risk_score = ensemble.get("composite_score") if ensemble else None
    if risk_score is not None:
        dims["risk"] = {"score": round(100.0 - risk_score, 1),
                        "weight": _WEIGHTS["risk"]}

    # Quality — already higher = better.
    q = quality.get("quality_score") if quality else None
    if q is not None:
        dims["quality"] = {"score": q, "weight": _WEIGHTS["quality"]}

    # Valuation — upside vs fair value.
    val_dim = _valuation_dimension(valuation.get("upside_pct") if valuation else None)
    if val_dim is not None:
        dims["valuation"] = {"score": val_dim, "weight": _WEIGHTS["valuation"]}

    # Momentum — already 0-100, higher = better.
    m = momentum.get("momentum_score") if momentum else None
    if m is not None:
        dims["momentum"] = {"score": m, "weight": _WEIGHTS["momentum"]}

    # Governance — invert the governance risk score.
    if governance and governance.get("governance_score") is not None:
        dims["governance"] = {
            "score":  round(100.0 - governance["governance_score"], 1),
            "weight": _WEIGHTS["governance"],
        }

    if not dims:
        return {
            "bcsi_score":  None,
            "bcsi_label":  "Unknown",
            "dimensions":  {},
            "confidence":  0,
        }

    total_w = sum(d["weight"] for d in dims.values())
    bcsi = round(
        sum(d["score"] * (d["weight"] / total_w) for d in dims.values()), 1
    )

    return {
        "bcsi_score":  bcsi,
        "bcsi_label":  _label_for(bcsi),
        "dimensions": {
            name: {"score": d["score"], "weight": round(d["weight"] / total_w, 3)}
            for name, d in dims.items()
        },
        "confidence":  round(len(dims) / len(_WEIGHTS) * 100),
    }
