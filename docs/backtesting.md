# Backtesting

The backtesting engine simulates portfolio performance on historical data.

## Quick Start

```python
from backend.services.backtest import BacktestEngine

engine = BacktestEngine(db)
result = await engine.run(
    tickers=["HDFCBANK", "ICICIBANK"],
    start_date="2024-01-01",
    end_date="2024-12-31",
    strategy="momentum",
)
print(result.sharpe_ratio, result.max_drawdown)
```

## Strategies

- `momentum` — buy top-N by trailing 3M return
- `low_risk` — buy bottom-N by composite risk score
- `value` — buy bottom-N by DCF discount

## Metrics Returned

| Metric | Description |
|---|---|
| Sharpe Ratio | Risk-adjusted return |
| Max Drawdown | Largest peak-to-trough decline |
| Annualised Return | CAGR over the backtest period |
| Win Rate | % of rebalance periods that were profitable |
