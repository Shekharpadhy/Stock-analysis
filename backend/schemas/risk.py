from pydantic import BaseModel
from typing import Optional

class RiskComponents(BaseModel):
    altman_z: Optional[float]; beneish_m: Optional[float]
    sentiment: Optional[float]; governance: Optional[float]

class RiskScoreOut(BaseModel):
    ticker: str; risk_score: float; components: RiskComponents
