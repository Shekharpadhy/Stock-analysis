"""
News sentiment — lexicon-based scoring on recent headlines.

Why lexicon, not LLM/transformer
────────────────────────────────
For an internal momentum signal, a curated financial-news lexicon is the
right cost/value tradeoff: predictable, offline, instant, no GPU.  When the
team wants nuanced sentiment we can swap the scorer for FinBERT behind the
same interface — `score_headlines(list[str]) -> dict` doesn't change.

Public surface
──────────────
  score_headlines(headlines)        Pure: list[str] → 0-100 score + breakdown
  fetch_headlines(ticker, days=14)  yfinance adapter — network-touching, kept
                                    behind a thin wall so tests stub it freely
  compute_news_score(ticker, days)  Convenience wrapper used by the momentum
                                    engine.  Returns the score dict (or None
                                    when fetch fails / no headlines).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Lexicons ──────────────────────────────────────────────────────────────────
# Tuned for financial / earnings headlines.  Weights matter: "fraud" should
# move the dial more than "miss"; "upgrade" more than "rise".

_POSITIVE: Dict[str, float] = {
    # Strong (3.0 each)
    "upgrade": 3.0, "outperform": 3.0, "beats": 3.0, "beat": 3.0,
    "record": 3.0, "surge": 3.0, "soars": 3.0, "rally": 3.0,
    "acquisition": 2.5, "buyback": 2.5, "dividend hike": 3.0,
    # Moderate (1.5 each)
    "raise": 1.5, "raised": 1.5, "growth": 1.5, "expansion": 1.5,
    "gain": 1.5, "gains": 1.5, "profit": 1.5, "profitable": 2.0,
    "strong": 1.5, "robust": 1.5, "improved": 1.5,
    # Light (1.0 each)
    "rise": 1.0, "rises": 1.0, "up": 0.5, "positive": 1.0,
    "win": 1.5, "approval": 1.5, "approved": 1.5,
}

_NEGATIVE: Dict[str, float] = {
    # Strong (3.0 each)
    "fraud": 4.0, "investigation": 3.0, "lawsuit": 3.0, "subpoena": 3.0,
    "bankruptcy": 5.0, "default": 3.5, "downgrade": 3.0, "delisted": 4.0,
    "restatement": 3.5, "scandal": 3.5, "probe": 2.5, "indictment": 4.0,
    # Moderate (1.5 each)
    "miss": 2.0, "misses": 2.0, "loss": 1.5, "losses": 1.5,
    "cut": 1.5, "warns": 2.0, "warning": 2.0, "decline": 1.5,
    "drop": 1.5, "fell": 1.5, "weak": 1.5, "slump": 2.0,
    "layoffs": 2.0, "restructuring": 1.5, "delay": 1.5,
    # Light (1.0 each)
    "fall": 1.0, "falls": 1.0, "down": 0.5, "negative": 1.0,
    "concern": 1.0, "concerns": 1.0, "risk": 0.5,
}

# Tokenize on word-ish runs.  Lower-case + strip punctuation before matching.
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")

# Compound phrases that must be matched whole-string (e.g. "dividend hike").
_COMPOUND_POS = [k for k in _POSITIVE if " " in k]
_COMPOUND_NEG = [k for k in _NEGATIVE if " " in k]


# ── Pure scorer ───────────────────────────────────────────────────────────────

def _score_one(headline: str) -> tuple[float, List[str]]:
    """
    Return the signed sentiment weight for a single headline + matched terms.
    Positive headlines yield positive scores, negative ones negative.
    """
    text = (headline or "").lower()
    matched: List[str] = []
    score = 0.0

    # Compound phrases first (they would otherwise be missed by tokenisation).
    for phrase in _COMPOUND_POS:
        if phrase in text:
            score += _POSITIVE[phrase]; matched.append(phrase)
    for phrase in _COMPOUND_NEG:
        if phrase in text:
            score -= _NEGATIVE[phrase]; matched.append(phrase)

    # Single-token matches.
    for tok in _TOKEN_RE.findall(text):
        if tok in _POSITIVE and tok not in matched:
            score += _POSITIVE[tok]; matched.append(tok)
        elif tok in _NEGATIVE and tok not in matched:
            score -= _NEGATIVE[tok]; matched.append(tok)

    return score, matched


def score_headlines(headlines: List[str]) -> Dict[str, Any]:
    """
    Aggregate sentiment over a list of headlines.

    Returns
    -------
        {
          "score":     float | None    # 0-100, None when no headlines
          "label":     str             # Bullish | Positive | Neutral | Negative | Bearish | Unknown
          "n":         int             # headlines processed
          "n_positive":int
          "n_negative":int
          "n_neutral": int
          "raw_sum":   float           # signed weight pre-normalisation
          "samples":   list of recent matched headlines + score
        }

    Mapping
    ───────
    The raw weighted sum is divided by `max(n, 5)` to dampen the impact of
    a single sensational headline, then squashed through a tanh sigmoid so
    a sum of ±6/headline saturates near 0/100.
    """
    if not headlines:
        return {
            "score": None, "label": "Unknown", "n": 0,
            "n_positive": 0, "n_negative": 0, "n_neutral": 0,
            "raw_sum": 0.0, "samples": [],
        }

    import math
    per_headline: List[tuple[str, float, List[str]]] = []
    raw_sum = 0.0
    n_pos = n_neg = n_neu = 0

    for h in headlines:
        s, matched = _score_one(h)
        per_headline.append((h, s, matched))
        raw_sum += s
        if   s > 0.5:  n_pos += 1
        elif s < -0.5: n_neg += 1
        else:          n_neu += 1

    # Damping divisor keeps tiny samples from over-rotating.
    avg = raw_sum / max(len(headlines), 5)
    # Saturate at +/-6 → ~98 / 2.
    score = round(50.0 + 50.0 * math.tanh(avg / 3.0), 1)

    if   score >= 70: label = "Bullish"
    elif score >= 58: label = "Positive"
    elif score >= 42: label = "Neutral"
    elif score >= 30: label = "Negative"
    else:             label = "Bearish"

    # Surface the most-emphatic headlines for the UI tooltip.
    samples = sorted(per_headline, key=lambda t: -abs(t[1]))[:5]
    return {
        "score":      score,
        "label":      label,
        "n":          len(headlines),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "n_neutral":  n_neu,
        "raw_sum":    round(raw_sum, 2),
        "samples":    [
            {"headline": h, "score": round(s, 2), "terms": terms}
            for h, s, terms in samples
        ],
    }


# ── yfinance adapter (the only network-touching function) ─────────────────────

def fetch_headlines(ticker: str, days: int = 14) -> List[str]:
    """
    Return headlines for `ticker` published within the last `days` days.

    yfinance's `Ticker.news` shape is `[{'title': str, 'providerPublishTime':
    unix_ts, ...}, ...]`.  We tolerate missing fields and just return what we
    can extract — a malformed response yields an empty list, never an error.
    """
    try:
        import yfinance as yf
        items = yf.Ticker(ticker.upper()).news or []
    except Exception as exc:                            # noqa: BLE001
        log.warning("news_sentiment: yfinance fetch failed for %s — %s",
                    ticker, exc)
        return []

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    out: List[str] = []
    for it in items:
        # yfinance has changed this shape across versions — handle both.
        content = it.get("content", it) if isinstance(it, dict) else {}
        title = content.get("title") or it.get("title")
        ts    = content.get("pubDate") or it.get("providerPublishTime")
        if not title:
            continue
        # ts may be unix-int or ISO-8601 string; either way be defensive.
        try:
            if isinstance(ts, (int, float)):
                published = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
            elif isinstance(ts, str):
                published = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                published = None
        except Exception:
            published = None
        if published is None or published >= cutoff:
            out.append(title)
    return out


def compute_news_score(ticker: str, days: int = 14) -> Optional[Dict[str, Any]]:
    """
    End-to-end: fetch + score.  Returns None on fetch failure / zero headlines
    so the momentum engine knows to renormalise.
    """
    headlines = fetch_headlines(ticker, days=days)
    if not headlines:
        return None
    return score_headlines(headlines)
