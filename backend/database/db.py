import os

from sqlalchemy import (create_engine, Column, String, Float, Integer, DateTime,
                        Text, Boolean, Date, UniqueConstraint)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from backend.config import settings

engine       = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()


class CompanyRecord(Base):
    __tablename__ = "companies"

    # ── Identity ──────────────────────────────────────────────────
    ticker      = Column(String, primary_key=True, index=True)
    name        = Column(String)
    sector      = Column(String, index=True)
    sub_sector  = Column(String)

    # ── Market / price ────────────────────────────────────────────
    market_cap          = Column(Float)
    current_price       = Column(Float)
    fifty_two_week_high = Column(Float)
    fifty_two_week_low  = Column(Float)
    beta                = Column(Float)

    # ── Income ────────────────────────────────────────────────────
    revenue_ttm          = Column(Float)
    revenue_growth_yoy   = Column(Float)
    earnings_growth      = Column(Float)   # decimal, e.g. 0.15
    net_margin           = Column(Float)
    roa                  = Column(Float)
    roe                  = Column(Float)

    # ── Valuation multiples ───────────────────────────────────────
    pe_ratio    = Column(Float)
    forward_pe  = Column(Float)
    peg_ratio   = Column(Float)
    ev_ebitda   = Column(Float)
    ev_revenue  = Column(Float)

    # ── Per-share ─────────────────────────────────────────────────
    eps_ttm     = Column(Float)
    eps_forward = Column(Float)

    # ── Balance sheet ─────────────────────────────────────────────
    debt_to_equity    = Column(Float)
    current_ratio     = Column(Float)
    total_cash        = Column(Float)
    total_debt        = Column(Float)
    shares_outstanding = Column(Float)

    # ── Cash flow ─────────────────────────────────────────────────
    free_cashflow = Column(Float)

    # ── Analyst data ──────────────────────────────────────────────
    analyst_target_mean = Column(Float)
    analyst_target_high = Column(Float)
    analyst_target_low  = Column(Float)
    analyst_count       = Column(Integer)
    recommendation      = Column(String)

    # ── Income distribution ───────────────────────────────────────
    dividend_yield = Column(Float)
    payout_ratio   = Column(Float)

    # ── Altman Z'-Score ───────────────────────────────────────────
    altman_z_score = Column(Float)
    altman_zone    = Column(String)   # Safe | Grey | Distress | Unavailable

    # ── Beneish M-Score ───────────────────────────────────────────
    beneish_m_score = Column(Float)
    beneish_flag    = Column(String)  # Low Manipulation Risk | Grey Zone | Likely Manipulator

    # ── Interest Coverage + FCF ───────────────────────────────────
    icr        = Column(Float)
    icr_label  = Column(String)
    fcf_margin = Column(Float)

    # ── Ensemble risk score (primary risk output) ─────────────────
    risk_score       = Column(Float)   # composite 0–100
    risk_label       = Column(String)  # Low Risk | Medium Risk | High Risk
    risk_confidence  = Column(Float)   # 0–100 data coverage score
    risk_flags       = Column(Text)    # JSON array of flag strings
    risk_components  = Column(Text)    # JSON breakdown by model
    sector_calibrated = Column(Boolean, default=False)

    # ── Fair value (per-share, base scenario) ─────────────────────
    dcf_fair_value       = Column(Float)
    pe_fair_value        = Column(Float)
    peg_fair_value       = Column(Float)
    analyst_consensus    = Column(Float)
    composite_fair_value = Column(Float)
    upside_pct           = Column(Float)
    valuation_label      = Column(String)
    valuation_confidence = Column(Float)

    # ── Scenario price targets ────────────────────────────────────
    bear_target           = Column(Float)
    base_target           = Column(Float)
    bull_target           = Column(Float)
    stretched_bull_target = Column(Float)

    # ── Entry / exit / stop levels ────────────────────────────────
    entry_zone_low  = Column(Float)
    entry_zone_high = Column(Float)
    trim_level      = Column(Float)
    hard_stop       = Column(Float)

    # ── Quality dimension (Piotroski / Graham / Magic Formula) ────
    quality_score     = Column(Float)
    quality_label     = Column(String)
    piotroski_f_score = Column(Integer)
    graham_number     = Column(Float)

    # ── BCSI composite (the headline number) ──────────────────────
    bcsi_score      = Column(Float)
    bcsi_label      = Column(String)
    bcsi_dimensions = Column(Text)     # JSON: {risk,quality,valuation,governance}
    bcsi_confidence = Column(Float)

    # ── Metadata ──────────────────────────────────────────────────
    last_updated = Column(DateTime, default=datetime.utcnow)


class PriceHistory(Base):
    """Daily closing prices — the price layer for backtesting and self-scoring."""
    __tablename__ = "price_history"

    id     = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, index=True, nullable=False)
    date   = Column(Date, index=True, nullable=False)
    close  = Column(Float, nullable=False)   # split/dividend-adjusted close
    volume = Column(Float)

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_price_ticker_date"),
    )


class BacktestObservation(Base):
    """One backtested prediction: the engine run on reconstructed point-in-time
    inputs for a past fiscal year, paired with the actual forward price return
    that followed."""
    __tablename__ = "backtest_observations"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    ticker          = Column(String, index=True, nullable=False)
    fy_end          = Column(Date, nullable=False)
    as_of           = Column(Date, index=True, nullable=False)
    sector          = Column(String)
    horizon_months  = Column(Integer, nullable=False)
    risk_score      = Column(Float)
    risk_label      = Column(String)
    valuation_label = Column(String)
    upside_pct      = Column(Float)
    base_target     = Column(Float)
    price_at_as_of  = Column(Float)
    forward_return_pct = Column(Float)   # actual; NULL when horizon runs past data
    created_at      = Column(DateTime, default=datetime.utcnow)


class Prediction(Base):
    """A forward-looking prediction snapshot recorded at analyze time, graded
    against the actual price once its horizon matures — the system's live,
    falsifiable track record."""
    __tablename__ = "predictions"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    ticker              = Column(String, index=True, nullable=False)
    predicted_at        = Column(Date, index=True, nullable=False)
    horizon_months      = Column(Integer, nullable=False)
    matures_on          = Column(Date, index=True, nullable=False)

    # prediction snapshot
    price_at_prediction = Column(Float)
    risk_score          = Column(Float)
    risk_label          = Column(String)
    valuation_label     = Column(String)
    upside_pct          = Column(Float)
    base_target         = Column(Float)
    bear_target         = Column(Float)
    bull_target         = Column(Float)

    # scoring — filled in once the horizon matures
    scored              = Column(Boolean, default=False, nullable=False)
    price_at_maturity   = Column(Float)
    actual_return_pct   = Column(Float)
    direction_correct   = Column(Boolean)
    base_hit            = Column(Boolean)

    created_at          = Column(DateTime, default=datetime.utcnow)


class SectorProfile(Base):
    """Data-calibrated sector metric distribution — re-estimated from
    accumulated CompanyRecord fundamentals to replace the hardcoded estimates
    in ensemble_risk.SECTOR_RISK_PROFILES."""
    __tablename__ = "sector_profiles"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    sector      = Column(String, index=True, nullable=False)
    metric      = Column(String, nullable=False)
    median      = Column(Float, nullable=False)
    spread      = Column(Float, nullable=False)
    sample_size = Column(Integer, nullable=False)
    updated_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("sector", "metric", name="uq_sector_profile"),
    )


class GovernanceRecord(Base):
    """India-specific governance signals — promoter pledge, SEBI enforcement,
    auditor changes, board independence — and the computed governance score.
    The differentiator: data that the generic global tools do not track."""
    __tablename__ = "governance_records"

    ticker = Column(String, primary_key=True, index=True)

    # ── Promoter pledge ───────────────────────────────────────────
    promoter_holding_pct      = Column(Float)
    promoter_pledge_pct       = Column(Float)   # % of promoter holding pledged
    promoter_pledge_pct_prior = Column(Float)   # ~1 year ago — for velocity

    # ── Auditor ───────────────────────────────────────────────────
    auditor_name             = Column(String)
    auditor_changed_recently = Column(Boolean)  # changed within ~2 years

    # ── SEBI enforcement ──────────────────────────────────────────
    sebi_action_pending = Column(Boolean)
    sebi_action_count   = Column(Integer)       # past actions on record

    # ── Board ─────────────────────────────────────────────────────
    board_size                 = Column(Integer)
    independent_director_count = Column(Integer)

    # ── Computed governance score ─────────────────────────────────
    governance_score = Column(Float)            # 0–100, higher = worse
    governance_label = Column(String)           # Strong | Adequate | Weak | Poor
    governance_flags = Column(Text)             # JSON array of flag strings

    updated_at = Column(DateTime, default=datetime.utcnow)


class AlertSubscription(Base):
    """
    A subscription to a specific alert condition for one ticker.

    Channels
    ────────
    At least one of `email` or `slack_webhook` must be set.
    If `slack_webhook` is NULL the global settings.alert_slack_webhook is used
    (when configured), so a row with only `email` still gets Slack delivery if
    the operator has a global webhook.

    Conditions
    ──────────
    See backend/services/alerts.VALID_CONDITIONS for the allowed values.
    `threshold` interpretation depends on the condition:
      risk_score_above   — numeric, e.g. 70.0
      quality_score_below — numeric, e.g. 40.0
      ml_prob_above      — decimal fraction, e.g. 0.60
      distress_zone      — threshold unused (NULL)
    """
    __tablename__ = "alert_subscriptions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    ticker       = Column(String, index=True, nullable=False)
    condition    = Column(String, nullable=False)   # one of VALID_CONDITIONS
    threshold    = Column(Float)                    # trigger level (NULL ok)
    email        = Column(String)                   # recipient email address
    slack_webhook = Column(String)                  # per-sub Slack webhook URL
    active       = Column(Boolean, default=True, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("ticker", "condition", "email",
                         name="uq_alert_ticker_condition_email"),
    )


class User(Base):
    """
    A registered platform user.

    Role values: "user" (default) | "admin"
    The admin role grants access to protected management endpoints.

    The built-in admin account (configured via env ADMIN_USERNAME /
    ADMIN_PASSWORD) never needs a DB row — it uses the legacy admin-credential
    check in auth.authenticate_admin(). Regular users created via
    POST /auth/register do get a DB row and authenticate with a hashed password.
    """
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    username        = Column(String, unique=True, nullable=False, index=True)
    email           = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role            = Column(String, default="user", nullable=False)   # "user" | "admin"
    is_active       = Column(Boolean, default=True, nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)


class WatchlistEntry(Base):
    """
    A single ticker in a user's watchlist.

    The `notes` field is an optional free-text memo (e.g. "bought at 145").
    """
    __tablename__ = "watchlist"

    id       = Column(Integer, primary_key=True, autoincrement=True)
    user_id  = Column(Integer, nullable=False, index=True)
    ticker   = Column(String, nullable=False, index=True)
    notes    = Column(Text)
    added_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Bring the database schema up to date by applying Alembic migrations.

    Migrations are the single source of truth for the schema — this replaces
    the old Base.metadata.create_all(), which could not evolve an existing
    database and silently diverged whenever a column was added.
    """
    from alembic.config import Config
    from alembic import command

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    command.upgrade(cfg, "head")
