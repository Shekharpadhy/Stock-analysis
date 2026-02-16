from pydantic import BaseModel
from typing import Optional

class CompanyOut(BaseModel):
    ticker: str; name: str; sector: str
    market_cap: Optional[float]; risk_score: Optional[float]
