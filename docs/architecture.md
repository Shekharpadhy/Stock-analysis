# System Architecture

## Overview

Banking Client Sector Intelligence aggregates financial, market, and NLP signals
to produce composite risk scores for banking-sector clients via a REST API.

## High-Level Diagram

```
┌──────────────┐      ┌────────────────────────────────┐
│   Frontend   │─────▶│  FastAPI  (backend/main.py)    │
│  (Chart.js)  │      │  JWT Auth · Rate Limiting       │
└──────────────┘      └───────────────┬────────────────┘
                                       │
              ┌────────────────────────┼──────────────────┐
              ▼                        ▼                   ▼
       ┌─────────────┐        ┌──────────────┐    ┌──────────────┐
       │  Services   │        │  SQLAlchemy  │    │    Redis     │
       │  Layer      │        │  ORM + DB    │    │    Cache     │
       └──────┬──────┘        └──────────────┘    └──────────────┘
              │
     ┌────────┴─────────────────────────┐
     ▼                                  ▼
┌──────────────────────┐    ┌──────────────────────┐
│  Scoring Models       │    │  Data Ingestion       │
│  Altman Z · Beneish M │    │  Yahoo Finance        │
│  Ensemble Risk        │    │  SEC EDGAR            │
│  Valuation (DCF)      │    │  News / NLP           │
└──────────────────────┘    └──────────────────────┘
```

## Key Service Responsibilities

| Service | Responsibility |
|---|---|
| `EnsembleRisk` | Fuses Z-score, M-score, sentiment, governance into one score |
| `Calibration` | Platt scaling / isotonic regression for probability outputs |
| `PITReconstruction` | Prevents lookahead bias in historical training data |
| `Backtest` | Event-driven strategy validation against historical data |
| `Valuation` | DCF and comparable-company valuation models |
| `Cache` | Redis-backed response caching with configurable TTL |
