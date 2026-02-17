def fmt_pct(value: float, decimals: int = 2) -> str:
    return f"{value * 100:.{decimals}f}%"

def fmt_currency(amount: float, symbol: str = "₹") -> str:
    if amount >= 1e7:
        return f"{symbol}{amount/1e7:.2f}Cr"
    if amount >= 1e5:
        return f"{symbol}{amount/1e5:.2f}L"
    return f"{symbol}{amount:,.2f}"

def fmt_risk_label(score: float) -> str:
    if score < 0.3: return "LOW"
    if score < 0.6: return "MEDIUM"
    if score < 0.8: return "HIGH"
    return "CRITICAL"
