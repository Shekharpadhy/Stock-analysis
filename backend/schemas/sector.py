from pydantic import BaseModel
from typing import Optional

class SectorOut(BaseModel):
    id: int; name: str; code: str; risk_score: Optional[float] = None
    class Config: from_attributes = True
