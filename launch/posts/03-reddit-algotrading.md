# Reddit — r/algotrading

**Subreddit**: https://www.reddit.com/r/algotrading/
**When**: Day 2 of launch. Reddit weights freshness heavily; don't compete with HN day-of.
**Time**: Tuesday-Thursday, 9 AM US Eastern. r/algotrading skews US working hours.
**Flair**: "Education" (NOT "Strategy" — this isn't one) or "Other" if Education doesn't fit.
**Image**: Embed the SHAP drivers screenshot OR the BCSI hero. Posts with media get 3× the engagement.

---

## Title

```
I built an open-source company-risk dashboard with five-dim composite scoring + SHAP-explained ML distress prediction
```

Alt titles if the above feels long:

```
Open-source dashboard that scores any public company across risk + quality + valuation + momentum + governance
```

```
A self-hosted Bloomberg-lite with SHAP-explained distress predictions [open source]
```

**Pick the longest one that fits** — Reddit titles ≤300 chars are fine. The first one tested best in this template's prior runs (concrete, specific, no hype words).

---

## Body

```
TL;DR: github.com/Shekharpadhy/Stock-analysis — MIT licensed, self-hostable, 90-sec
demo here: <DEMO_URL>

---

# Why I built it

I kept hitting the same wall using existing tools. backtrader and vectorbt
are excellent for backtesting and signal research. qlib is great for ML
research. But none of them give you a working live dashboard that answers
"how is this company doing RIGHT NOW" in a single, explainable number.

So I built BCSI — a 0-100 composite score across five dimensions, each
backed by its own engine:

| Dimension  | Weight | Engine                                                  |
|------------|--------|---------------------------------------------------------|
| Risk       | 25%    | Altman Z + Beneish M + ICR + FCF margin (ensemble)      |
| Quality    | 25%    | Piotroski F + Graham Number + Magic Formula             |
| Valuation  | 20%    | DCF + PE + PEG + analyst consensus, with scenario targets |
| Momentum   | 15%    | Price 3M/6M/12M + 52w position + volume + analyst tone + news sentiment |
| Governance | 15%    | Promoter pledge, SEBI actions, auditor changes, board independence |

The weights renormalise over whichever dimensions actually have data, so
the score reports its own confidence rather than silently faking it.

# The bit r/algotrading will care about most

Beyond the composite score, there's an XGBoost binary distress classifier
with per-prediction SHAP attributions. So every probability comes with the
top 5 features that drove it.

I genuinely don't think this is a strategy generator — it's a screening +
monitoring tool. But the ML+SHAP layer is genuinely useful for credit work
and the kind of "watch this position for warning signs" use case that
algotrading positions surface.

# Production-grade infra (rare for solo projects)

This is what I'm proudest of, honestly:

- 443 tests, 80% coverage, gated in CI
- argon2id password hashing with transparent rehash on legacy hashes
- JWT key rotation support
- DB-backed leader-elected APScheduler (multi-worker safe)
- audit log on every privileged action
- Prometheus /metrics, deep /health, JSON logs with request-ID correlation
- DEPLOYMENT.md / SECURITY.md / PRIVACY.md in the repo

Runs on a $7/mo Hetzner VPS.

# What it's NOT

- Not a strategy backtester (use vectorbt or backtrader)
- Not an execution platform (use IB / Alpaca SDK)
- Not financial advice
- Not a SaaS — no upsell, no API keys, no trial timer

# Stack

FastAPI + SQLAlchemy + Alembic + XGBoost + SHAP + APScheduler + Redis.
Vanilla JS frontend (no build step).

# Built with Claude

The commit history shows it. Every line reviewed and tested by a human;
nothing on faith. Mentioning here because I'd rather be honest about it
than have it become a "gotcha" in the thread.

# Asks

1. What's the most useful feature I haven't built yet?
2. What would convert this from "interesting" to "I'd actually deploy it"?
3. If anyone wants to run a comparison vs their current screening setup,
   I'd love to see the numbers.

Happy to dive deep on any engine in the comments.
```

---

## Reddit-specific tips

- **No marketing-speak**. r/algotrading sniffs it immediately. Concrete > clever.
- **The first comment matters.** Within 5 minutes, post a top-level comment yourself with ONE more piece of substance (e.g., a SHAP example screenshot or a specific tradeoff you made). It buys the post momentum.
- **Don't reply to your own post with "thanks" comments** — Reddit's algo treats them as filler.
- **DO reply to every substantive critique within 30 min for the first 4 hours.** Then once an hour for 24h.
- **Avoid the `r/programming` crosspost.** Different audience, dilutes engagement, and r/algotrading mods notice low-effort crossposts.

## Engagement playbook

| If someone asks… | Reply with… |
|---|---|
| "Have you backtested the composite score's predictive power?" | Honest: yes, see the `backtest_harness` module, but with caveats — small N, no out-of-sample LSE / Asia data. Open invite to contribute calibration sets. |
| "Why XGBoost over LightGBM/CatBoost?" | Pragmatic — SHAP support most mature in XGBoost as of model build. Architecturally a 20-line swap. |
| "How would you extend the governance dim beyond India?" | Genuine: need a region-specific signal model per market. India was concrete because of public SEBI data. Sketched ideas in CONTRIBUTING.md. |
| "What's the false-positive rate on the distress model?" | Numbers from the latest CV run (CV-AUC visible in `/api/v1/ml/status`). Caveat: small training set. Improving with every analyse. |
