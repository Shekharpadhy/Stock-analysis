from pydantic import BaseModel
from datetime import date
from typing import List

class BacktestRequest(BaseModel):
    tickers: List[str]; start_date: date; end_date: date
    strategy: str = "momentum"; rebalance_freq: str = "monthly"

class BacktestResult(BaseModel):
    sharpe_ratio: float; max_drawdown: float
    annualized_return: float; win_rate: float
