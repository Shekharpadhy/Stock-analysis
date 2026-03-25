# Performance

## Benchmarks (local, M2 MacBook)

| Endpoint | P50 | P95 | P99 |
|---|---|---|---|
| GET /health | 2ms | 4ms | 8ms |
| GET /sectors | 18ms | 45ms | 90ms |
| GET /companies/{ticker}/risk | 120ms | 280ms | 450ms |
| POST /backtest | 800ms | 2.1s | 4.5s |

## Caching Strategy

Redis TTLs (configurable in `config/cache.yaml`):
- Sector summaries: 1 hour
- Company risk scores: 15 min
- Price history: 5 min
- Backtest results: 24 hours

## Scaling Tips

- Use `--workers 4` with uvicorn for CPU-bound scoring
- Add a Redis cluster for high-throughput caching
- Partition the `price_history` table by year for large datasets
