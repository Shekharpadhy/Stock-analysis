# Deployment Guide

## Prerequisites

- Docker ≥ 24 and Docker Compose ≥ 2
- A PostgreSQL 15 instance (or use the bundled compose service)
- A Redis 7 instance (or use the bundled compose service)

## Local Development

```bash
# 1. Install Python deps
make dev-install

# 2. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL, REDIS_URL, SECRET_KEY, ALPHA_VANTAGE_KEY

# 3. Start backing services
make docker-up

# 4. Run migrations
make migrate

# 5. Start the API server
make run
# API available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

## Production (Docker Compose)

```bash
docker-compose -f docker-compose.yml up -d
```

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL DSN e.g. `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | Redis DSN e.g. `redis://localhost:6379/0` |
| `SECRET_KEY` | JWT signing secret — generate with `openssl rand -hex 32` |
| `ALPHA_VANTAGE_KEY` | Market data API key |
| `DEBUG` | Set to `true` for verbose logs (default: `false`) |

## Health Check

```
GET /health   → 200 OK  {"status": "healthy", "db": "ok", "cache": "ok"}
```
