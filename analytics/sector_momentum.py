def momentum_score(prices, lookback=126):
    return prices.pct_change(lookback)

