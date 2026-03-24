# Data Sources

## Market Data — Yahoo Finance

Accessed via `yfinance` library. Provides:
- OHLCV price history (daily, weekly, monthly)
- Fundamental data (P/E, EPS, market cap)
- Dividend and split history

## Regulatory Filings — SEC EDGAR

Accessed via the EDGAR API (`https://data.sec.gov`). Provides:
- 10-K and 10-Q financial statements
- Altman Z-Score inputs (EBIT, total assets, liabilities, etc.)
- Beneish M-Score inputs (receivables, assets, COGS)

## News — Web Scraping + RSS

News articles are fetched from financial RSS feeds and scraped sources.
Text is processed by the NLP sentiment pipeline.

## Data Freshness

| Source | Update Frequency |
|---|---|
| Price history | Real-time / end-of-day |
| Fundamentals | Quarterly (on filing) |
| Sentiment | Every 15 minutes |
| Risk scores | Hourly |
