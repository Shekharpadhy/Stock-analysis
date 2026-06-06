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

    # Financial Modeling Prep — primary fundamentals source.  Free tier is
    # 250 requests/day, covers US + NSE/BSE India fully.  When unset, the
    # app falls back to yfinance (less reliable on cloud IPs).  Set via
    # the FMP_API_KEY env var in production.
    fmp_api_key: str = ""
    database_url: str = "sqlite:///./intelligence.db"
    redis_url: str = "redis://localhost:6379/0"
    # Cache TTL for the yfinance fundamentals payload.  4 hours is the
    # sweet spot — fundamentals don't change intra-day (quarterly reports
    # land at known times), and a longer TTL dramatically reduces the
    # number of Yahoo API hits, which dodges rate-limit windows.  After a
    # ticker is analysed once, the next 4 hours of requests for it are
    # served from Redis without touching Yahoo at all.
    cache_ttl: int = 14400   # 4 hours

    # CORS — comma-separated allowlist (no "*" in production)
    cors_origins: str = "http://localhost:8765,http://localhost:3000"

    # Per-IP rate limits (slowapi syntax, e.g. "120/minute")
    rate_limit_default: str = "120/minute"
    rate_limit_analyze: str = "10/minute"
    # Tight throttles on auth endpoints to slow brute-force attempts.  Pick
    # numbers that are friendly to legitimate retypes but punitive at scale.
    rate_limit_auth_login:    str = "10/minute"
    rate_limit_auth_register: str = "5/hour"
    rate_limit_auth_reset:    str = "3/hour"
    rate_limit_auth_verify:   str = "20/hour"
    # Master toggle — disabled in tests so the suite doesn't trip its own
    # throttles. Always true in production.
    rate_limit_enabled: bool = True

    # Public-facing base URL used to build verify / reset email links.
    # Must include scheme + host (no trailing slash).  Render auto-injects
    # RENDER_EXTERNAL_URL at runtime; the resolved_public_base_url helper
    # below transparently prefers PUBLIC_BASE_URL when set, then falls back
    # to RENDER_EXTERNAL_URL, then to the localhost default.  This lets the
    # Render blueprint stay schema-clean (no fromService.envVarKey conflict)
    # while still producing correct email links on the very first boot.
    public_base_url: str = "http://localhost:8000"

    # Lifetimes (in hours) for account-lifecycle tokens.
    email_verification_ttl_hours: int = 24
    password_reset_ttl_hours:     int = 1

    # JWT authentication — JWT_SECRET and ADMIN_PASSWORD MUST be overridden
    # via env before deployment. The defaults below are intentionally insecure.
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    # Optional secondary verifier — accept tokens signed with the previous
    # secret during a rotation window.  New tokens are always signed with
    # JWT_SECRET. Empty string disables the fallback.
    jwt_secret_previous: str = ""
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

    # ── Derived accessors ─────────────────────────────────────────────────────

    def resolved_public_base_url(self) -> str:
        """
        Return the URL we should embed in outgoing emails.

        Resolution order:
            1. PUBLIC_BASE_URL — explicitly set by the operator (always wins)
            2. RENDER_EXTERNAL_URL — Render auto-injects this; on first deploy
               PUBLIC_BASE_URL is usually unset, so this is the natural fallback
            3. The localhost default — last resort for dev / docker-compose
        """
        import os
        if self.public_base_url and self.public_base_url != "http://localhost:8000":
            return self.public_base_url.rstrip("/")
        render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
        if render_url:
            return render_url.rstrip("/")
        return self.public_base_url.rstrip("/")

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
