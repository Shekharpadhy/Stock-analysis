from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
