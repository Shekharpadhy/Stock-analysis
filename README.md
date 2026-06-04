<h1 align="center">BCSI</h1>

<p align="center">
  <b>Open-source company risk intelligence — with a single score, real explanations, and a live dashboard.</b><br/>
  <sub>Five-dimensional scoring · ML distress prediction with SHAP · multi-user watchlists & alerts · WebSocket prices · self-hosted</sub>
</p>

<p align="center">
  <a href="#quickstart"><img alt="quickstart" src="https://img.shields.io/badge/quickstart-5_minutes-1f6feb"></a>
  <img alt="tests" src="https://img.shields.io/badge/tests-443_passing-3fb950">
  <img alt="coverage" src="https://img.shields.io/badge/coverage-80%25-3fb950">
  <img alt="python" src="https://img.shields.io/badge/python-3.10+-1f6feb">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-black">
</p>

<p align="center">
  <b>🚀 Live demo:</b> <a href="https://bcsi-web.onrender.com"><code>bcsi-web.onrender.com</code></a>
  &nbsp;·&nbsp;
  <a href="https://render.com/deploy?repo=https://github.com/Shekharpadhy/Stock-analysis"><img alt="Deploy to Render" src="https://render.com/images/deploy-to-render-button.svg" height="22"></a>
</p>

<p align="center">
  <sub>Free Render tier sleeps after 15 min of inactivity — first request may take ~30s to wake.</sub>
</p>

<p align="center">
  <i>BCSI = Banking Client Sector Intelligence.</i><br/>
  <i>Think Bloomberg-lite, but open source, explainable, and self-hostable for &lt; $50/mo.</i>
</p>

---

## Why this exists

Every analyst, PM, and credit officer ends up building the same dashboard: pull fundamentals, compute a risk score, eyeball valuation, watch for red flags. Existing tools each do one slice — backtesting libraries, technical analysis, ML notebooks — and none of them give you a single, honest, **explainable** answer to *"how is this company doing?"*.

BCSI answers that question with one number — and shows you exactly how it got there.

```
NVDA   BCSI 78.4   Strong   (coverage: 100%)
              ──────────────
              Risk        82  ████████████████░░░░  (25%)
              Quality     85  █████████████████░░░  (25%)
              Valuation   58  ███████████░░░░░░░░░  (20%)
              Momentum    91  ██████████████████░░  (15%)
              Governance  72  ██████████████░░░░░░  (15%)
```

Each dimension is its own engine. Each engine is auditable in the codebase. Each prediction comes with feature-level SHAP attributions. No black boxes, no API keys, no monthly fee.

---

## What's in the box

> 📸 _**Add a demo GIF here:** `docs/demo.gif` — 30 seconds showing analyze → BCSI hero → accordion expand → alert fire. This single asset triples README → ⭐ conversion._

### The five BCSI dimensions

| Dimension | Engine | What it actually measures |
|---|---|---|
| **Risk** (25%) | Ensemble of Altman Z, Beneish M, ICR, FCF margin | Default + manipulation + solvency risk in one normalised score |
| **Quality** (25%) | Piotroski F + Graham Number + Magic Formula | Earnings quality, not just earnings level |
| **Valuation** (20%) | DCF + PE + PEG + analyst consensus, scenario targets | Upside/downside to a defensible fair value |
| **Momentum** (15%) | Price 3M/6M/12M + 52w position + volume + analyst tone + news sentiment | Tape signal blended with sell-side rotation |
| **Governance** (15%) | Promoter pledge + SEBI actions + auditor changes + board indep. | India-specific signals that the global tools miss |

Weights renormalise over whatever data is available — the score never silently fakes confidence it doesn't have.

### Beyond scoring

- **🤖 ML distress prediction** — XGBoost binary classifier on 14 features, with **per-prediction SHAP explanations** ranking which drivers matter for *this* company.
- **📡 Real-time price streaming** — WebSocket feed pushes price updates straight into the dashboard with flash animations.
- **🔔 Smart alerts** — Email + Slack notifications, edge-triggered when conditions flip (e.g. risk crosses 75, Altman Z drops into Distress) with a 24-hour cooldown so you never get spammed.
- **👥 Multi-user with watchlists** — Per-user portfolios, auto-created default alerts on every ticker you watch.
- **📊 Portfolio analytics** — Aggregate watchlists into BCSI distribution, sector exposure, and top/bottom holdings.
- **🔍 Audit trail** — Every privileged action (login, retrain, alert fire) recorded; queryable via `/api/v1/audit`.
- **🩺 Production observability** — `/health` (deep), `/metrics` (Prometheus), JSON structured logs, request-IDs across every log line.

---

## How does it compare?

| | BCSI | qlib | vectorbt | backtrader | Bloomberg |
|---|---|---|---|---|---|
| **Composite multi-dim score** | ✅ 5 dims | — | — | — | ❌ no single number |
| **Real-time dashboard** | ✅ WebSocket | — | — | — | ✅ (paid) |
| **ML + SHAP explainability** | ✅ | partial | — | — | ❌ |
| **Multi-user + alerts** | ✅ | — | — | — | ✅ (paid) |
| **Self-hostable** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Production infra** (audit, RBAC, observability) | ✅ | — | — | — | n/a |
| **Cost** | $0 | $0 | $0 / paid pro | $0 | **$24k+ / seat / yr** |

BCSI is closer to a **finished platform** than a research library. If you want to write trading strategies in Jupyter, use `qlib` or `vectorbt`. If you want a working dashboard you can deploy today, BCSI.

---

## Quickstart

Five minutes from clone to a running dashboard.

```bash
git clone https://github.com/Shekharpadhy/Stock-analysis.git
cd bcsi

# Option 1 — Docker (recommended)
docker compose up -d
open http://localhost:8000

# Option 2 — Native Python
pip install -r requirements.txt
uvicorn backend.main:app --reload
open http://localhost:8000
```

Then in the dashboard:

1. Click **Sign in** → **Register** to create an account.
2. Enter `AAPL` (or any US ticker) and click **Analyze**.
3. Watch BCSI compute in real time. Expand any accordion to see the per-engine inputs and SHAP attributions.
4. Add a few more tickers, hit **My Portfolio** to see the aggregate view.

Need API access? Grab an admin token:

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
     -d "username=admin&password=change-me"

# Then analyze a ticker via API
curl -X POST "http://localhost:8000/api/v1/companies/analyze?ticker=NVDA" \
     -H "Authorization: Bearer <token>"
```

Full API docs at <http://localhost:8000/docs> (OpenAPI / Swagger UI).

---

## Architecture

```
                          ┌─────────────────────┐
   yfinance ──┐           │     FastAPI         │   ──> WebSocket /ws/prices
   SEC EDGAR ─┼──> ingest │   ┌─────────────┐   │   ──> REST /api/v1/...
   News feeds ┘           │   │ 6 engines:  │   │
                          │   │  risk       │   │
                          │   │  quality    │   │
                          │   │  valuation  │   │
                          │   │  momentum   │   │
                          │   │  governance │   │
                          │   │  ml + SHAP  │   │
                          │   └──────┬──────┘   │
                          │          ▼          │
                          │     BCSI compose    │
                          └──────────┬──────────┘
                                     ▼
                               PostgreSQL
                                     │
                          ┌──────────┴──────────┐
                          │   APScheduler       │   <── leader-elected
                          │  · alert sweeps     │       across N workers
                          │  · ML retrain       │
                          │  · sector recalib.  │
                          └─────────────────────┘
```

- **FastAPI + Pydantic** for the API surface
- **SQLAlchemy + Alembic** for ORM + migrations
- **XGBoost + SHAP** for distress prediction
- **APScheduler** for background jobs with DB-backed leader election
- **slowapi + JWT (argon2id) + audit log** for security
- **Vanilla JS + WebSocket** frontend (no build step — open `index.html` and go)

Detailed module map in [`ROADMAP.md`](ROADMAP.md). Production setup in [`DEPLOYMENT.md`](DEPLOYMENT.md). Security controls in [`SECURITY.md`](SECURITY.md). Data handling in [`PRIVACY.md`](PRIVACY.md).

---

## Production-ready, not toy-ready

This isn't a 200-line proof of concept. Every box that matters for actually running this in front of users is checked:

- **443 tests, 80% coverage**, gated in CI (`--cov-fail-under=78`)
- **Auth hardening** — argon2id passwords, email verification, password reset, JWT key rotation, per-IP rate limiting on every auth endpoint
- **Account enumeration resistance** — `/auth/password-reset/request` returns 202 whether or not the email matches
- **Audit log** — every privileged action recorded with actor + target + timestamp
- **Multi-worker safe** — APScheduler runs with DB-backed leader election; you can scale the web tier without double-firing jobs
- **Observable** — Prometheus `/metrics`, deep `/health` (DB + scheduler + ML), JSON logs with request-ID correlation
- **Documented** — DEPLOYMENT.md, SECURITY.md, PRIVACY.md cover env hardening, key rotation, GDPR-shaped data requests

If you're an operator, the [pre-deployment checklist](DEPLOYMENT.md#6-pre-deployment-checklist) is what you actually want to read.

---

## Roadmap

- ✅ **v1.0** — public-ready. Auth hardening, email flows, multi-worker scheduler, governance docs.
- 🚧 **v1.1** — TOTP/MFA, external pen test, session revocation, admin UI pages for audit/scheduler/ML.
- 🔮 **v1.2** — FinBERT swap for the lexicon sentiment scorer; news source diversification beyond yfinance.
- 🔮 **v1.3** — alternative data integrations (insider trading, options flow, short interest).

Detailed version history in [`CHANGELOG.md`](CHANGELOG.md).

---

## A note on provenance

This project was built in close collaboration with [Claude](https://claude.ai) — the commit history shows it explicitly. Every line was reviewed and tested by a human; nothing was merged on faith. If you're allergic to AI-assisted code, that's fine, but it'd be dishonest to hide it.

The result: more breadth in the same wall-clock time, the same care per module, and a paper trail of design decisions any reviewer can follow.

---

## Contributing

Pull requests welcome. The bar:

1. Run `pytest tests/ --cov=backend --cov-fail-under=78` locally — must pass.
2. Update `CHANGELOG.md` under `## Unreleased`.
3. For schema changes, add an Alembic migration in `alembic/versions/`.

Run `ruff check backend/` for the (advisory) lint pass.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide.

---

## License

MIT. Use it for anything you want. If it makes you money or saves your team time, [star the repo](https://github.com/Shekharpadhy/Stock-analysis) — that's how this stays alive.

---

<p align="center">
  <sub>Built for analysts who want a real answer, not a chart.</sub>
</p>

<!-- v2 in development -->


<!-- v2 link -->


<!-- v1.1.0-rc1 -->

