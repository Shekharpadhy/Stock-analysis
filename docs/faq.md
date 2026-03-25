# Frequently Asked Questions

**Q: Which exchanges are supported?**
A: NSE and BSE (India) via Yahoo Finance tickers (e.g., `HDFCBANK.NS`).

**Q: How often are risk scores updated?**
A: Hourly by default. Adjust `ttl.risk_score` in `config/cache.yaml`.

**Q: Can I add a custom scoring model?**
A: Yes — implement `BaseScorer` in `backend/services/` and register it in `EnsembleRiskService`.

**Q: Is historical backtesting accurate?**
A: Point-in-time reconstruction (`PITReconstructionService`) prevents lookahead bias, but survivorship bias in the universe is not corrected.

**Q: How do I add a new GICS sector?**
A: Update `config/sectors.yaml` and re-run `alembic upgrade head`.
