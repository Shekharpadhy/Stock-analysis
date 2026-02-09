RISK_THRESHOLDS = {"low": 0.3, "medium": 0.6, "high": 0.8, "critical": 1.0}
CACHE_TTL = {"sector": 3600, "company": 900, "price": 300, "risk": 600}
GICS_SECTORS = [
    "Financials","Information Technology","Health Care",
    "Energy","Industrials","Consumer Discretionary",
    "Consumer Staples","Materials","Utilities","Real Estate","Communication Services",
]
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7
