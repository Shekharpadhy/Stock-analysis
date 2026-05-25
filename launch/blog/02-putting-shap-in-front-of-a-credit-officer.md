# Putting SHAP in front of a credit officer

> **Cross-post target**: dev.to (technical-but-finance audience) → Medium → LinkedIn.
> **Length**: ~1,600 words.
> **Hook**: This is the "I'd actually use this" piece — concrete, screenshots, real ticker walkthroughs. Lead with this when the audience is finance professionals.

---

Most ML in finance fails the same way: the model is right, the credit officer doesn't trust it, and the prediction never gets used. The reason is almost always the same — the officer can't explain a decision to a regulator, a CFO, or themselves if the model is a black box.

This post is about a specific architectural choice — embedding SHAP per-prediction attributions into the production response, not the research notebook — and why it changes whether the model actually gets adopted.

I'll walk through a real prediction the system makes today, show what the output looks like, and explain how each piece supports the workflow of someone who actually has to defend a credit call.

## The model

BCSI ships an XGBoost binary classifier trained on 14 features extracted from `CompanyRecord`. Target variable is binary distress, defined as either:

1. Actual forward 6-month return below -20% (when historical backtest observations are available), or
2. Altman Z-score zone == "Distress" (fallback when forward returns are insufficient).

Features (14):

```
Balance sheet:    debt_to_equity, current_ratio, icr, fcf_margin
Profitability:    net_margin, roa, roe, revenue_growth_yoy
Valuation:        pe_ratio, ev_ebitda
Scoring outputs:  altman_z_score, beneish_m_score, risk_score
Quality:          quality_score
```

Training is a `xgb.XGBClassifier` with 300 trees, max depth 4, learning rate 0.05, subsampled rows and columns at 80%. Standard hyperparameters; nothing exotic. CV-AUC on the latest training run is in the 0.82-0.88 range depending on dataset composition (small N, caveat below).

The interesting part isn't the model. Anyone can train an XGBoost on financial features. The interesting part is what the API returns:

```json
{
  "ticker": "GME",
  "distress_probability": 0.7234,
  "distress_label": "High Distress Risk",
  "shap_values": {
    "debt_to_equity":    0.412,
    "fcf_margin":       -0.318,
    "altman_z_score":   -0.295,
    "icr":               0.187,
    "net_margin":       -0.151,
    "roe":              -0.124,
    "risk_score":        0.098,
    "...": "..."
  },
  "top_drivers": [
    {"feature": "debt_to_equity",  "raw_value": 3.4,  "shap":  0.412, "direction": "increases_risk"},
    {"feature": "fcf_margin",      "raw_value": -8.2, "shap": -0.318, "direction": "reduces_risk"},
    {"feature": "altman_z_score",  "raw_value": 0.8,  "shap": -0.295, "direction": "reduces_risk"},
    {"feature": "icr",             "raw_value": 1.2,  "shap":  0.187, "direction": "increases_risk"},
    {"feature": "net_margin",      "raw_value": -3.1, "shap": -0.151, "direction": "reduces_risk"}
  ],
  "model_meta": {
    "trained_at": "2026-05-25T03:00:00+00:00",
    "cv_auc":     0.84
  }
}
```

Read that response carefully. Especially the `top_drivers` array. Every single number in there is something a credit officer can defend in a meeting.

## What `top_drivers` actually means

Each entry has four fields, and the combination is what makes it usable.

**`feature`** is the input variable name. Not a model coefficient — the actual financial concept. Debt-to-equity. Interest coverage ratio. Beneish M-score. These are terms that already exist in the analyst's mental model.

**`raw_value`** is the company's input for that feature. `debt_to_equity: 3.4` means GME (in this hypothetical run) has $3.40 of debt per $1 of equity. The officer can sanity-check this against their own data source.

**`shap`** is the Shapley value — the model's attribution of this feature's contribution to the prediction. Positive SHAP increases distress risk; negative decreases it. The magnitude is comparable across features (this is the property SHAP guarantees that other "feature importance" methods don't).

**`direction`** is the human-readable interpretation: "increases_risk" or "reduces_risk". The officer doesn't need to know what a Shapley value is — the verb is right there.

Now look at the top driver: `debt_to_equity` of 3.4, contributing +0.412 to the prediction in the direction of "increases_risk".

This is what the officer says in the meeting:

> *"The model rates this as high distress because debt-to-equity is 3.4 — well above the sector median — and that single feature is the largest contributor to the score. Free cash flow margin and Altman Z-score actually push the prediction toward 'safe', but they're outweighed by the leverage signal."*

That sentence is **defensible**. Auditable. Regulator-friendly. The model isn't a black box producing a number; it's an explicit weighing of factors that the analyst can second-guess.

## Why this matters more than CV-AUC

Most ML-in-fintech writing focuses on model accuracy. CV-AUC 0.84 vs 0.86. Different feature engineering. Calibration plots.

I think this focus is mostly wasted effort, for a structural reason: **the credit officer doesn't get to choose between models with subtly different AUCs**. They get to choose between using the model or ignoring it. The decision is binary, and it hinges almost entirely on whether they trust the output enough to attach their name to it.

A 0.84-AUC model with SHAP attributions gets used.

A 0.92-AUC model that outputs only a probability gets opened in someone's notebook, looked at suspiciously, and never makes it to the credit committee deck.

This is the gap that kills 90% of ML deployments in regulated industries. It's not a modelling problem; it's an interface problem.

The architectural choice — embedding SHAP attribution into the production API response, not as a separate "explainability layer" you have to call afterward — moves the explanation from "research artifact" to "first-class output." It's the difference between explainability that exists (in a notebook) and explainability that operates (on a dashboard the officer actually opens).

## The performance cost

SHAP attribution isn't free. `TreeExplainer.shap_values()` takes ~5-10ms for a single XGBoost prediction with 300 trees and 14 features on a modern CPU. That's roughly 3-5× the time of the bare `predict_proba` call.

For most production systems this is irrelevant — the inference latency is dominated by network and DB roundtrips. The SHAP cost disappears in the noise.

But it does affect throughput at scale. If you wanted to score 50,000 names per minute, the SHAP overhead becomes material. The right architecture is to compute SHAP only on the names actually surfaced to a user — lazy attribution, not eager — which is what the BCSI API does (`GET /api/v1/ml/predict/{ticker}` is the only endpoint that returns SHAP; batch screening uses the cheaper `analyze` flow).

This is a useful pattern in general: separate the **predict path** (cheap, batch-friendly) from the **explain path** (more expensive, requested per-name-of-interest). Most ML APIs conflate the two.

## What this code looks like

The whole SHAP integration is one ~10-line section of the predict function:

```python
# In backend/services/ml_model.py

prob = float(model.predict_proba(X_imp)[0, 1])
shap_vals = expl.shap_values(X_imp)[0]
shap_dict = {col: round(float(v), 4) for col, v in zip(FEATURE_COLS, shap_vals)}

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

return {
    "ticker": ticker,
    "distress_probability": round(prob, 4),
    "shap_values": shap_dict,
    "top_drivers": drivers[:5],
    ...
}
```

That's it. The `explainer` object is built once at training time and stored in the model bundle so inference is cheap. The sort by `-abs(shap)` puts the most-impactful features first, regardless of direction. The top-5 slice is for the UI; the full `shap_values` dict is there for clients that want to do their own analysis.

Ten lines of code. Different product.

## Caveats I'd want any reader to know

This is honest about its limitations:

- **Training set is small.** With ~30 labelled companies in the demo data, CV-AUC numbers are noisy. The model is genuinely better the more data the operator accumulates. The model is retrained weekly via APScheduler.
- **Forward-return labels are leaky.** The retraining job updates the model with newly-matured labels, but a company that recovers from "Distress" zone before the forward window matures gets ambiguously labelled. The codebase handles this with a `DISTRESS_RETURN_THRESHOLD` (-20%) gate; it's an opinion, not a fact.
- **Survivor bias.** Public companies are all survivors at the moment of training. The model is necessarily under-trained on tail events.
- **The 14 features are US-listed-friendly.** Indian small-caps often have data gaps in ROA/ROE/EV/EBITDA. The renormalisation pattern from [the previous blog post] applies inside the ML stage too — missing features fall back to column medians at predict time.

None of these are showstoppers. All of them are stated in the docs. The model is offered as a directional signal, not a verdict.

## The takeaway

If you build an ML model for financial decisions and the only output is a probability:

- It will be technically correct
- It will be ignored

If you build the same model and the output is a probability **plus the top-5 feature attributions, each with raw value, signed SHAP contribution, and a human-readable direction**:

- It will be technically correct
- It will be used

The interface IS the product, in a regulated industry. The model is a commodity. The trust is the differentiator.

---

**BCSI ships the model + SHAP + real-time UI + multi-user infra as one open-source platform. github.com/<your-handle>/bcsi. MIT, self-hosted, no upsell. The `/api/v1/ml/predict/{ticker}` endpoint demoed above returns the JSON exactly as shown.**
