# Deployment Guide

This guide covers what you need to know before running the Banking Client
Sector Intelligence platform in any non-development environment.

The app is a single FastAPI process, fronted by a reverse proxy, talking to
PostgreSQL and Redis.  Heavy work (ML training, sector recalibration, alert
sweeps) runs in-process via APScheduler.

---

## 1. Required environment variables

Before `APP_ENV=production`, the application **refuses to start** unless
you've overridden these. The check lives in `Settings.validate_for_production()`
and fires from the FastAPI lifespan, so a misconfiguration fails fast at boot,
not at the first sensitive request.

| Variable          | What it is                                | Bad default to replace               |
| ----------------- | ----------------------------------------- | ------------------------------------ |
| `JWT_SECRET`      | HMAC key for signing access tokens        | `dev-only-insecure-secret-change-me` |
| `ADMIN_PASSWORD`  | Built-in admin account password           | `change-me`                          |

Generate a strong `JWT_SECRET` with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Recommended additional production env:

```bash
APP_ENV=production
DATABASE_URL=postgresql+psycopg2://user:pass@db-host:5432/bcsi
REDIS_URL=redis://redis-host:6379/0
CORS_ORIGINS=https://app.example.com,https://admin.example.com
ALERT_SMTP_HOST=smtp.sendgrid.net
ALERT_SMTP_USER=apikey
ALERT_SMTP_PASSWORD=<sendgrid-api-key>
ALERT_EMAIL_FROM=alerts@example.com
ALERT_SLACK_WEBHOOK=https://hooks.slack.com/services/...
SCHEDULER_ENABLED=true
JWT_EXPIRE_MINUTES=60
```

The full list of tunables is in [`backend/config.py`](backend/config.py).
Every Pydantic `Settings` field becomes a `SCREAMING_SNAKE_CASE` env var.

---

## 2. Database

### 2.1. Schema migrations

Alembic is the single source of truth for the schema. The application runs
`alembic upgrade head` automatically on startup (see `init_db()` in
`backend/database/db.py`). To run migrations manually:

```bash
alembic upgrade head           # apply all pending
alembic current                # show current revision
alembic history --verbose      # see the migration tree
```

### 2.2. Backups

The platform stores everything in PostgreSQL:

- `companies` — analysis results (regenerable via `/analyze` but slow)
- `price_history`, `backtest_observations`, `predictions` — historical
  signal data; expensive to rebuild
- `users`, `watchlist`, `alert_subscriptions` — user-owned state; loss
  here is user-visible
- `audit_log` — append-only; required for compliance reviews

Take a daily `pg_dump --format=custom` and ship to off-site object storage.
A monthly restore drill is the only test that catches silent corruption.

---

## 3. Process model and the scheduler-singleton constraint

**The scheduler must run in exactly one process.** APScheduler is
in-process — running N gunicorn workers with `SCHEDULER_ENABLED=true` will
fire every cron job N times.

Two clean ways to comply:

### 3.1. Single-worker app + separate scheduler-only process

```bash
# Web tier (any number of replicas; SCHEDULER_ENABLED=false)
gunicorn backend.main:app -k uvicorn.workers.UvicornWorker \
    -w 4 -b 0.0.0.0:8000

# Scheduler tier — exactly ONE replica; SCHEDULER_ENABLED=true,
# behind a separate Docker service / Kubernetes Deployment.
python -m backend.main      # or use the same gunicorn cmd with -w 1
```

### 3.2. Single-worker monolith (small deployments)

```bash
gunicorn backend.main:app -k uvicorn.workers.UvicornWorker -w 1
```

For most pilot/demo deployments option 3.2 is plenty.  Cross over to 3.1
when sustained request throughput approaches ~50 RPS.

---

## 4. Reverse proxy and TLS

The app does not terminate TLS itself.  Front it with Caddy, nginx, or a
managed load balancer:

```caddy
# Caddyfile example
api.example.com {
    encode gzip
    reverse_proxy bcsi:8000
    @ws {
        path /api/v1/ws/*
    }
    reverse_proxy @ws bcsi:8000
}
```

WebSocket support requires the proxy to forward `Upgrade` / `Connection`
headers — Caddy and nginx do this automatically; check your provider's
docs if you're using a managed load balancer.

---

## 5. Observability

### 5.1. Health checks

```
GET  /api/v1/health
```

Reports an overall `status` of `ok`, `degraded`, or `down`, and per-component
states for `database`, `scheduler`, and `ml_model`.  HTTP status is
`503` when the DB is down — point your load balancer's readiness probe here.

### 5.2. Prometheus metrics

```
GET  /api/v1/metrics
```

Plain-text Prometheus exposition.  Counters currently emitted:

- `analyses_total{sector}` — `/companies/analyze` invocations
- `alerts_fired_total{condition}` — alert dispatches
- `ml_predictions_total` — `/ml/predict` invocations
- `ml_trainings_total{result}` — model retrains (success/failure)
- `scheduler_runs_total{job}` — scheduler job firings
- `websocket_connections_total` — cumulative WS clients

The endpoint is unauthenticated by design (scrapers can't carry bearer
tokens). Gate access at the network layer: bind a private subnet, or
restrict the `/metrics` path to your monitoring VPC at the proxy.

### 5.3. Audit log

```
GET  /api/v1/audit?actor=&action=&limit=100
```

Admin-only. Every privileged action (admin login, ML train, scheduler
trigger, user register) emits a row.  Query by actor or action.

---

## 6. Pre-deployment checklist

- [ ] `APP_ENV=production`
- [ ] `JWT_SECRET` and `ADMIN_PASSWORD` set to strong random values
- [ ] `DATABASE_URL` points at a production Postgres (not SQLite)
- [ ] `REDIS_URL` reachable from the app (or accept the warm-cache miss)
- [ ] `CORS_ORIGINS` enumerates only the domains you actually serve
- [ ] Alerts: SMTP creds OR Slack webhook configured (or both)
- [ ] Scheduler: exactly one process running with `SCHEDULER_ENABLED=true`
- [ ] Reverse proxy terminates TLS and forwards WebSocket upgrades
- [ ] Health-check probe wired to `/api/v1/health`
- [ ] Prometheus scrape configured for `/api/v1/metrics`
- [ ] `pg_dump` scheduled daily, off-site backup verified
- [ ] Audit-log retention policy decided (no auto-rotation yet — wire one
      if your compliance regime requires it)

---

## 7. Upgrade procedure

1. **Take a `pg_dump` of production.**
2. Read the new release's `CHANGELOG.md`, especially the "Migrations" section.
3. Roll a single canary instance: `git pull && docker compose up -d --build`
   on one host.  Confirm `/api/v1/health` reports `ok`.
4. Spot-check the audit log for any unexpected `failed: True` extras.
5. Roll the rest of the fleet.

Migrations are forward-compatible by convention; downgrade scripts exist
(see each `alembic/versions/*.py`) but treat them as a break-glass
mechanism, not a routine workflow.
