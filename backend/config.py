import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


# Default values that MUST be overridden before deploying to production.
# Centralised so validate_for_production() can list them in the error message.
_INSECURE_DEFAULTS = {
    "jwt_secret":     "dev-only-insecure-secret-change-me",
    "admin_password": "change-me",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_port: int = 8000
    sec_user_agent: str = "ResearchBot research@example.com"
    database_url: str = "sqlite:///./intelligence.db"
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl: int = 900   # 15 minutes — TTL for cached yfinance fundamentals

    # CORS — comma-separated allowlist (no "*" in production)
    cors_origins: str = "http://localhost:8765,http://localhost:3000"

    # Per-IP rate limits (slowapi syntax, e.g. "120/minute")
    rate_limit_default: str = "120/minute"
    rate_limit_analyze: str = "10/minute"

    # JWT authentication — JWT_SECRET and ADMIN_PASSWORD MUST be overridden
    # via env before deployment. The defaults below are intentionally insecure.
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    admin_username: str = "admin"
    admin_password: str = "change-me"

    # Self-scoring track record — comma-separated prediction horizons (months)
    prediction_horizons: str = "3,6,12"

    # ── Alert delivery ─────────────────────────────────────────────────────────
    # SMTP email alerts (leave empty to disable)
    alert_smtp_host: str = ""
    alert_smtp_port: int = 587
    alert_smtp_user: str = ""
    alert_smtp_password: str = ""
    alert_email_from: str = "alerts@bcsi.example.com"

    # Slack webhook URL (leave empty to disable)
    alert_slack_webhook: str = ""

    # Risk-score threshold above which an alert fires (0–100)
    alert_risk_threshold: float = 70.0

    # Background scheduler — set to false in tests / one-shot CLI runs
    scheduler_enabled: bool = True

    # ── Logging ──────────────────────────────────────────────────────────────
    # `text` for dev, `json` for prod log-shippers (Datadog, Loki, ES, ...)
    log_format: str = "text"
    log_level:  str = "INFO"

    # ── Validation hooks ──────────────────────────────────────────────────────

    def is_production(self) -> bool:
        return self.app_env.lower() in ("production", "prod")

    def validate_for_production(self) -> None:
        """
        When APP_ENV=production, REFUSE to run with insecure defaults.

        Called from main.py at app startup.  In non-production envs we only
        log a warning so dev workflows aren't disrupted.
        """
        leaks = [
            field for field, default in _INSECURE_DEFAULTS.items()
            if getattr(self, field) == default
        ]
        if not leaks:
            return

        if self.is_production():
            raise RuntimeError(
                "Refusing to start in production with insecure defaults: "
                f"{', '.join(leaks)}.  Set strong values via env vars before "
                "deploying — see DEPLOYMENT.md."
            )
        log.warning(
            "config: insecure defaults active (%s).  Safe for dev — but you "
            "must override these before APP_ENV=production.", ", ".join(leaks),
        )


settings = Settings()
