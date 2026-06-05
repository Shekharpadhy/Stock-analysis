# Show HN post

**Submit to**: https://news.ycombinator.com/submit
**Best time**: Tuesday or Wednesday, 8–10 AM US Pacific (peaks the timezone bell curve)
**Pinned tab**: Open it, set a 4-hour timer, refresh every 20 min to reply within the first hour of any comment.

---

## Title

```
Show HN: BCSI – open-source company risk scoring with five dimensions and SHAP
```

**Why this title**:
- Starts with "Show HN:" (required for the category).
- "BCSI" — short, googleable, no buzzwords.
- "open-source" — non-negotiable for HN; signals "you can read the code."
- "company risk scoring" — concrete and searchable.
- "five dimensions and SHAP" — the unique angles, not generic claims.
- Under 80 chars.

---

## URL field

Your GitHub repo (NOT the demo site — HN weights `github.com` submissions higher and the title chip renders better).

```
https://github.com/Shekharpadhy/Stock-analysis
```

If you have a hosted demo, link it in the body instead.

---

## Body

```
Hi HN — I spent the last few months building BCSI, an open-source platform
that gives any public company a single composite risk score with full
per-engine explainability.

The motivation: every quant tool I've used does ONE thing well. Backtrader
is for backtests. vectorbt is for vectorised analysis. qlib is for ML
research. Nothing gives a credit officer or PM a single, honest, explainable
answer to "how is this company doing right now."

BCSI computes a 0-100 score from five dimensions:

  * Risk (25%) — ensemble of Altman Z, Beneish M, ICR, FCF margin
  * Quality (25%) — Piotroski F-score + Graham Number + Magic Formula
  * Valuation (20%) — DCF + PE + PEG + analyst consensus
  * Momentum (15%) — price returns + 52w position + volume + analyst tone
                     + lexicon-based news sentiment
  * Governance (15%) — India-specific signals (promoter pledge, SEBI
                       actions, auditor changes, board independence)

Weights renormalise over whichever dimensions have data, so the score never
silently fakes confidence it doesn't have — it reports its own coverage.

For credit work specifically there's also an XGBoost distress-prediction
model with per-prediction SHAP attributions — every probability comes with
the top 5 features that drove it.

The thing I'm proudest of isn't the scoring — it's that this is built like
production software, not a research project: 443 tests at 80% coverage,
argon2id passwords with rehash-on-verify, JWT key rotation, leader-elected
APScheduler so you can run it multi-worker, request-ID correlation across
JSON logs, Prometheus /metrics, audit log, deep /health. DEPLOYMENT.md,
SECURITY.md, PRIVACY.md all in the repo.

What it isn't: a SaaS, a strategy backtester, or financial advice. It's a
self-hostable analyst dashboard. Costs a Hetzner VPS to run.

Demo video (90s): <YOUTUBE_LINK>
Repo: https://github.com/Shekharpadhy/Stock-analysis

What would you change?
```

---

## After submitting

**Hour 0–4 (critical)**:
- Refresh comments every 20 min. Reply to every single one within 30 min.
- Lead with substance, not gratitude. "Good question — here's why I made that tradeoff…" beats "Thanks for the kind words!".
- If someone says it's "just yfinance + sklearn", agree with the parts that are true and point at the integration / production work that isn't.
- DON'T defend hard — HN smells defensive immediately. Acknowledge real critiques.

**Hour 4–24**:
- Reply rate can drop to once per hour.
- If the post is climbing: post a follow-up tweet linking to the HN discussion.
- If the post is flat: don't try to revive it. Move to Reddit per the calendar.

**Critique-handling cheatsheet**:

| Likely comment | Response angle |
|---|---|
| "Just another fintech dashboard" | Point at the comparison table. The ML+SHAP+governance combo is genuinely uncommon. |
| "AI-generated slop" | Point at the test suite (443 tests, 80% coverage, gated in CI) and a specific module reviewers can read end-to-end. The code earns trust by being readable and tested. |
| "yfinance is unreliable" | Agreed — it's the rate-limited free tier. Architecturally a thin adapter; swap-in alternative documented in CONTRIBUTING. |
| "Where's the moat?" | There isn't one and that's the point — MIT-licensed, self-hosted, no SaaS upsell. |
| "Indian governance metrics?" | Genuine differentiator vs Bloomberg/Finviz — they don't track promoter pledge / SEBI enforcement. |
| "Why not use [other lib]?" | Specific answer per lib (qlib is research, vectorbt is backtest, backtrader is execution). |

---

## What "success" looks like

- 50+ upvotes in the first 2 hours → likely front page
- 100+ stars on the repo within 24 hours
- 5–10 "this is genuinely useful" comments
- 1–2 issues filed (people only file issues for projects they think are worth it — issues are stars-in-disguise)

If you land on the front page, the secondary tweet thread (see `02-twitter-thread.md`) should fire ~3 hours into the HN run, not before. Synergy compounds; firing them simultaneously dilutes both.
