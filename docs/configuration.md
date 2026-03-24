# Configuration Reference

All configuration is managed via environment variables (`.env`) and YAML files under `config/`.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | PostgreSQL async DSN |
| `REDIS_URL` | Yes | `redis://localhost:6379/0` | Redis DSN |
| `SECRET_KEY` | Yes | — | 32-byte hex JWT secret |
| `ALPHA_VANTAGE_KEY` | No | — | Market data API key |
| `DEBUG` | No | `false` | Enable debug mode |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity |

## YAML Configuration Files

- `config/api.yaml` — server, rate-limiting, CORS settings
- `config/cache.yaml` — Redis TTL values
- `config/logging.yaml` — logging format and handlers
- `config/features.yaml` — feature flags
