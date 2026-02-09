import re

TICKER_RE = re.compile(r"^[A-Z0-9.]{1,12}$")

def validate_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if not TICKER_RE.match(t):
        raise ValueError(f"Invalid ticker: {ticker!r}")
    return t

def validate_positive(value: float, name: str = "value") -> float:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value

def validate_date_range(start, end) -> None:
    if start > end:
        raise ValueError("start_date must be before end_date")
