# Risk Models

## Altman Z-Score

Predicts corporate bankruptcy using five financial ratios:
- Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5
- Z > 2.99: Safe; 1.81–2.99: Grey; < 1.81: Distress

## Beneish M-Score

Detects earnings manipulation using 8 financial indices.
- M < −2.22: Unlikely manipulator
- M > −2.22: Likely manipulator

## Ensemble Risk Score

Combines:
1. Financial distress (Altman Z + Beneish M)
2. Market signals (momentum, volatility)
3. Sentiment score (NLP on recent news)
4. Governance score (ESG + board quality)
5. Valuation discount (DCF vs market price)

Weights are calibrated using Platt scaling on historical defaults.
