import numpy as np

def rolling_beta(returns, market, window=60):
    cov = returns.rolling(window).cov(market)
    var = market.rolling(window).var()
    return cov / var

