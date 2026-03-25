# Data Dictionary

## Table: `price_history`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| ticker | VARCHAR(20) | Stock ticker symbol |
| date | DATE | Trading date |
| open | FLOAT | Opening price |
| high | FLOAT | Intraday high |
| low | FLOAT | Intraday low |
| close | FLOAT | Closing price |
| volume | BIGINT | Shares traded |

## Table: `sector_profiles`

| Column | Type | Description |
|---|---|---|
| id | INTEGER | Primary key |
| sector_name | VARCHAR(100) | GICS sector name |
| risk_score | FLOAT | Latest composite risk score |
| updated_at | DATETIME | Last score update timestamp |
