# Why every quant tool computes the same score badly

> **Cross-post target**: Personal blog → Medium → dev.to → LinkedIn article (in that order; 48-hour gap between each so canonical Google index lands on your blog).
> **Length**: ~1,800 words.
> **Reading time**: 9 minutes.
> **Hook**: This is the *intellectually interesting* angle — the design-rationale piece that quant Twitter respects. Lead with this for credibility.

---

Last year I tried to monitor 40 holdings across three regions using existing tools.

I had backtrader for strategy work, vectorbt for signal analysis, qlib for an ML side project, and a giant Google Sheet for the actual "is this company OK" check. Every Monday morning I'd pull the same fundamentals into the same cells, eyeball the same red flags, and try to convince myself I hadn't missed something material.

The Sheet got to 200 rows of conditional formatting before I gave up and built the thing I actually needed. It turned out the thing I actually needed didn't exist as open source, and I think the reason is that everyone who tries to build it gets one specific design decision wrong.

Here's the decision: **how do you compose multiple signals into a single number when not all of them are available?**

## The naive approach

You weight your signals. Risk gets 25%, Quality 25%, Valuation 20%, Momentum 15%, Governance 15%. You compute each one, multiply, sum. Done.

Until you realise that:

- A US-listed company has no SEBI enforcement history (the Indian regulator), so your Governance signal is `None`.
- A pre-revenue biotech has no meaningful PE ratio, so your Valuation signal collapses.
- A newly-IPO'd company has no 12-month price history, so half your Momentum signal is unavailable.
- A penny stock has no Piotroski score because the financial statements are too sparse, so your Quality signal partly degrades.

Now what? You have four options, and three of them are wrong:

1. **Skip the company.** "Insufficient data." This is what most tools do. It's correct and useless: the companies you most need to evaluate are exactly the ones with the spottiest data.
2. **Substitute the mean.** Pretend a missing Quality score is "average". This is the worst option — you're injecting fake confidence into the composite, and the user has no way to tell which numbers are real.
3. **Hard-code defaults.** Treat missing data as "neutral" (50/100). Same problem as #2, slightly less aggressive.
4. **Renormalise.** Drop the missing dimension, spread its weight proportionally across the dimensions you do have, and **report coverage as a first-class output**.

Option 4 is what BCSI does, and it's the design decision that makes the difference between a score you can trust and one you can't.

## What renormalisation actually looks like

Here's the relevant code, lightly trimmed:

```python
def compute_bcsi(ensemble, valuation, quality, governance=None, momentum=None):
    dims = {}

    if ensemble.get("composite_score") is not None:
        dims["risk"] = {"score": 100 - ensemble["composite_score"], "weight": 0.25}

    if quality and quality.get("quality_score") is not None:
        dims["quality"] = {"score": quality["quality_score"], "weight": 0.25}

    val_dim = _valuation_dimension(valuation.get("upside_pct"))
    if val_dim is not None:
        dims["valuation"] = {"score": val_dim, "weight": 0.20}

    m = momentum.get("momentum_score") if momentum else None
    if m is not None:
        dims["momentum"] = {"score": m, "weight": 0.15}

    if governance and governance.get("governance_score") is not None:
        dims["governance"] = {"score": 100 - governance["governance_score"], "weight": 0.15}

    if not dims:
        return {"bcsi_score": None, "confidence": 0, ...}

    total_w = sum(d["weight"] for d in dims.values())
    bcsi = sum(d["score"] * (d["weight"] / total_w) for d in dims.values())

    return {
        "bcsi_score": round(bcsi, 1),
        "dimensions": {
            name: {"score": d["score"], "weight": round(d["weight"] / total_w, 3)}
            for name, d in dims.items()
        },
        "confidence": round(len(dims) / 5 * 100),
    }
```

Three things to notice:

**One**: the function never silently substitutes a default. A `None` dimension is simply absent from the output. The user always knows which signals were available.

**Two**: `total_w` is computed dynamically from whichever dimensions made it in. The weights you read in the API response are the **effective** weights for this specific company, not the design-time weights. A US company missing Governance shows Risk=27%, Quality=27%, Valuation=22%, Momentum=18% — not the nominal 25/25/20/15.

**Three**: the response carries `confidence` — literally the fraction of dimensions present. A 78 BCSI with confidence=60% is a fundamentally different statement than a 78 with confidence=100%. The score reports its own epistemic state.

## Why this is the part that's hard

The temptation when building a composite score is to optimise the composition function. Different weights. Different non-linearities. Maybe a learned weighting from data. Maybe a Bayesian update over priors. There's a near-infinite design space here and it's all *fun* — it feels like the interesting problem.

It's not the interesting problem.

The interesting problem is: **what does your score mean when it's partial?** Because the real world is always partial. Real companies have spotty data. Real users want to trust the number. If your composite collapses when one signal is missing, or worse, fabricates a value to keep going, the entire premise of "we computed a single score" falls apart on day two.

I spent maybe 40% of the engine-design time on the composition function and 60% on the missing-data semantics. That ratio is, I think, why most attempts at this end up looking like dashboards that are technically right and operationally useless.

## The same principle, one layer down

The composition pattern recurs inside individual engines too.

Take Momentum. It blends five sub-signals: 3M/6M/12M price returns, 52-week position, volume trend, analyst recommendation strength, news sentiment. Of those:

- Price returns require 12 months of history (often missing for IPOs).
- 52-week position requires at least 52 weeks of data.
- Volume trend requires reliable volume history (often missing for thinly-traded names).
- Analyst recommendation is available only for covered names.
- News sentiment requires recent headlines (often empty for small-caps).

So Momentum itself is a partial composite. Same pattern: collect whichever sub-signals exist, renormalise their weights, report sub-confidence. The Momentum dimension then feeds into BCSI carrying both its value AND its internal coverage state, and BCSI's own renormalisation gracefully handles a Momentum dimension whose internal coverage is 40%.

The hierarchy of coverage is composable, which is the only way it can survive being the foundation of a real product. You don't get to demand clean data; you handle the data you have, transparently.

## What this gets you that nothing else does

The thing this enables — and I don't see other tools doing it — is the ability to say:

> *"AAPL has BCSI = 78, confidence 100%. JPM has BCSI = 75, confidence 80%. RELIANCE.NS has BCSI = 71, confidence 60%."*

All three numbers are usable. They mean different things. The user knows the difference. **Bloomberg doesn't tell you which of its scores is data-starved.** Neither does Simply Wall St. Neither does any quant library I've reviewed.

And once the user gets used to the confidence number being on every output, they instinctively start asking the right follow-up questions for the partial ones. "BCSI 71 confidence 60% — what's missing?" → they expand the dimensions panel → they see Momentum and Governance both have lower internal coverage → they know to do additional manual diligence on those two areas. The system has guided them to do the right thing.

This is, in the end, the only thing that justifies the existence of a composite score. If the user can't trust it AND can't tell when not to, you've built a roulette wheel with extra steps.

## The unsexy lesson

I had a lot of fun building the actual engines. The Altman Z-score is a 1968 paper that still works. The Piotroski F-score is nine yes/no questions you can compute from any 10-K. SHAP explanations on an XGBoost model are technically interesting and visually compelling. The momentum lexicon was satisfying to tune.

None of those decisions matter as much as the boring one — what happens when a signal is missing.

If you're building anything that composes signals (and most useful software does), the engineering pattern that pays off long-term is:

1. Make each signal optional from day one.
2. Bake confidence/coverage into the data structure, not added later.
3. Renormalise weights at composition time, never pre-bake them.
4. Surface the coverage number to the user, prominently, every time.

The "single number" the user actually wants includes the meta-information about how trustworthy it is. Treating coverage as a first-class output is the difference between a dashboard people read and a dashboard people trust.

The code is open source. The composition function above is ~30 lines. The hard part isn't the math.

---

**BCSI is at github.com/Shekharpadhy/Stock-analysis. MIT licensed. Five-dimension composite scoring with confidence as a first-class output, ML distress prediction with SHAP explanations, real-time prices, multi-user watchlists. Self-hosted on a $7/mo VPS.**

*Read time was 9 minutes. If it was worth that, a star is the cheapest way to repay it.*
