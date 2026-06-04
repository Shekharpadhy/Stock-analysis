#!/usr/bin/env bash
# Container entrypoint.
#
# Migrations are applied here — once, deterministically, before the server
# starts — rather than relying solely on the app's startup hook. This avoids
# the multi-worker race the code review flagged: if the app is ever scaled to
# multiple workers, only this single entrypoint step runs the DDL.
set -euo pipefail

echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
python -m alembic upgrade head

# Honour $PORT when the platform assigns it (Render, Fly, Heroku, Cloud Run);
# default to 8000 for local docker-compose.
PORT="${PORT:-8000}"
echo "[entrypoint] Starting API server on :${PORT}..."
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}"
