from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def now_ist() -> datetime:
    return datetime.now(IST)

def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)

def date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)

def trading_days_between(start: date, end: date) -> int:
    return sum(1 for d in date_range(start, end) if d.weekday() < 5)
