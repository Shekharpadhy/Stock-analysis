# API Reference

**Base URL:** `http://localhost:8000`

All endpoints except `/health` require a Bearer token header:
```
Authorization: Bearer <access_token>
```

---

## Authentication

### `POST /auth/login`
Returns access and refresh tokens.

**Body:** `{"username": "...", "password": "..."}`
**Response:** `{"access_token": "...", "refresh_token": "...", "token_type": "bearer"}`

### `POST /auth/refresh`
Exchange a refresh token for a new access token.

---

## Sector Intelligence

### `GET /sectors`
List all tracked GICS sectors with summary risk metrics.

### `GET /sectors/{sector_id}`
Full risk profile for a single sector.

### `GET /companies/{ticker}/risk`
Composite risk score for a company.

**Response:**
```json
{
  "ticker": "HDFCBANK",
  "sector": "Financials",
  "risk_score": 0.28,
  "components": {
    "altman_z": 4.1,
    "beneish_m": -2.9,
    "sentiment": 0.71,
    "governance": 0.88,
    "valuation": 0.45
  }
}
```

### `GET /price-history/{ticker}`
OHLCV price history for a ticker.

### `POST /backtest`
Submit a strategy configuration and receive backtest results.

### `GET /health`
Service health and dependency status (no auth required).
