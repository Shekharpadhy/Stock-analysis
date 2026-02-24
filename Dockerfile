# ─────────────────────────────────────────────────────────────────────────────
# Banking Client Sector Intelligence — API container
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Unbuffered stdout/stderr (reliable logs); no .pyc files.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# curl is used by the docker-compose healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first so this layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY backend/ ./backend/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
COPY frontend/ ./frontend/
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x docker-entrypoint.sh

# The SQLite database lives on a mounted volume so it survives restarts.
RUN mkdir -p /app/data

EXPOSE 8000

# Entrypoint applies migrations once, then starts the server.
ENTRYPOINT ["./docker-entrypoint.sh"]
