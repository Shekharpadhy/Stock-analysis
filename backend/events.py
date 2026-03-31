from enum import Enum

class EventType(str, Enum):
    INGESTION_COMPLETE = "ingestion.complete"
    RISK_SCORED = "risk.scored"
    BACKTEST_DONE = "backtest.done"
    CACHE_INVALIDATED = "cache.invalidated"
    ALERT_TRIGGERED = "alert.triggered"
