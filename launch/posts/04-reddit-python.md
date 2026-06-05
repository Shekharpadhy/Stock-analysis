# Reddit — r/Python

**Subreddit**: https://www.reddit.com/r/Python/
**When**: Day 4 of launch. Wait for the Show HN + r/algotrading wave to clear so this is fresh, not a rehash.
**Time**: Monday-Wednesday, 10 AM US Eastern. r/Python skews international; this window catches US morning and Europe afternoon.
**Flair**: "Showcase" (required by sub rules for project announcements).
**Critical**: Read the [r/Python posting rules](https://www.reddit.com/r/Python/wiki/sidebar) before submitting. They aggressively remove low-effort showcases. The "What My Project Does / Target Audience / Comparison" template is mandatory.

---

## Title

```
[Showcase] BCSI — open-source company risk scoring built on FastAPI, XGBoost, and SHAP
```

The `[Showcase]` prefix is conventional even when you also set the flair. Be explicit; helps moderators.

---

## Body — using the r/Python mandatory template

```
# What My Project Does

BCSI is a self-hosted dashboard that computes a 0-100 risk score for any
publicly traded company by ensembling outputs from five domain-specific
engines: balance-sheet risk (Altman + Beneish + ICR), earnings quality
(Piotroski), valuation (DCF + PE + PEG), momentum (price + volume +
analyst + news sentiment), and governance (India-specific signals).

It also includes an XGBoost binary distress-prediction model with
per-prediction SHAP feature attributions, real-time WebSocket price
streaming, per-user watchlists with email/Slack alerts, and portfolio
aggregation.

It's an MIT-licensed Python web app, not a library. You self-host it on
a VPS and analysts use it through a web UI.

# Target Audience

Built for:

- Buy-side analysts and credit officers who currently F5 a spreadsheet
- Quant developers who want a working monitoring layer alongside their
  research notebooks
- Banking/finance teams who want a transparent, explainable risk score
  without Bloomberg's $24k/seat tag
- Anyone curious about how to wire FastAPI + XGBoost + SHAP + APScheduler
  into a production-grade application

It is NOT for: backtesting strategies (use vectorbt), automating execution
(use IB/Alpaca), or anything that constitutes financial advice.

# Comparison

| Tool          | What it is                         | How BCSI differs                              |
|---------------|------------------------------------|-----------------------------------------------|
| backtrader    | Python backtesting framework       | BCSI is live monitoring, not strategy testing |
| vectorbt      | Vectorised analysis library        | BCSI ships a UI + multi-user infra            |
| qlib          | Quant research / ML library        | BCSI is a finished platform, not a toolkit    |
| finviz / Simply Wall St | Hosted screening dashboards | BCSI is self-hosted + fully transparent      |
| Bloomberg     | Enterprise terminal ($$$/seat)     | BCSI is $0/seat, open code, but US/India only |

# Technical highlights (the r/Python audience will care)

- FastAPI + SQLAlchemy 2.0 + Alembic + Pydantic v2
- 443 tests at 80% coverage, gated in CI (`--cov-fail-under=78`)
- argon2id password hashing with transparent rehash from legacy schemes
- JWT key rotation via dual-secret verifier (`JWT_SECRET_PREVIOUS`)
- APScheduler with DB-backed leader election (multi-worker safe)
- Request-ID middleware propagating via `contextvars.ContextVar`
- Structured JSON logging with automatic request_id correlation
- Custom Prometheus metrics registry (no `prometheus_client` dep —
  ~50 lines for what we needed)
- Vanilla JS frontend, no build toolchain (deliberate)

The [SECURITY.md](https://github.com/Shekharpadhy/Stock-analysis/blob/main/SECURITY.md)
and [DEPLOYMENT.md](https://github.com/Shekharpadhy/Stock-analysis/blob/main/DEPLOYMENT.md)
might be more interesting than the engine code itself if you've never
wired a production FastAPI app end-to-end.

# Links

- Repo: https://github.com/Shekharpadhy/Stock-analysis
- Demo video (90s): <DEMO_URL>
- Live demo: <DEMO_SITE_URL>

# Asks

What would make this useful to YOUR Python work? Specifically interested
in feedback on:

1. The metrics registry pattern (lightweight Prometheus-compatible without
   the `prometheus_client` dep) — overbuilt or sensible?
2. The leader-elected scheduler — is the DB-lease pattern obvious or did
   I reinvent something better-known?
3. The dimension renormalisation (weights re-spread over present
   components rather than penalising missing data) — sound or sketchy?
```

---

## r/Python specific tips

- **Mods enforce the template**. Skip a section and your post gets removed without warning.
- **No "what do you think?" without specifics**. r/Python downvotes vague asks. The three numbered asks at the bottom are the format that converts.
- **Don't post on weekends**. Engagement is half of weekday levels and you waste your one shot at this sub for ~30 days (the mods soft-throttle repeat showcases).
- **Reply to every code-question with code**. r/Python is technical — gif/screenshot replies don't land. Paste the actual snippet from the codebase.
- **If anyone says "this should be a library"**: explain it's a platform on purpose; the engines ARE importable as modules but ship pre-wired for the dashboard.

## Common r/Python flame-bait

| Bait | Don't | Do |
|---|---|---|
| "AI slop" | Get defensive | Link to a specific PR / test file. Code speaks. |
| "Yet another fintech project" | Pretend uniqueness | Concede the saturation; point at the specific gap (composite + SHAP + India governance) you filled |
| "Why FastAPI not Django/Flask?" | "Because it's modern" | Specific reasons: async WebSocket for prices, Pydantic for schema, OpenAPI for free. |
| "Why not Polars?" | "Pandas works" | Honest: Pandas was the path of least resistance; specific pieces (PriceHistory aggregations) are good Polars candidates and would PR-welcome |
| "Code in `routes.py` is too long" | Reflexive defense | Agreed — listed as a TODO in CONTRIBUTING; happy to split if someone wants the issue |
