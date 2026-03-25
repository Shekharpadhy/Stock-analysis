# Troubleshooting

## API returns 500 on startup

Check that Alembic migrations have been run:
```bash
make migrate
```

## Redis connection refused

Ensure Redis is running:
```bash
docker-compose up -d redis
```

## Slow risk score calculation

Enable caching in `config/features.yaml`:
```yaml
features:
  cache_responses: true
```

## Database connection pool exhausted

Increase `max_overflow` in `backend/database/db.py` or scale the API horizontally.

## Tests fail with `asyncio` errors

Make sure `pytest-asyncio` is installed and `asyncio_mode = "auto"` is set in `pyproject.toml`.
