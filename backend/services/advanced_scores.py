"""
Advanced risk scoring models:
  - Altman Z'-Score  (non-manufacturing, Altman 2000)
  - Beneish M-Score  (earnings manipulation detector, Beneish 1999)
  - Interest Coverage Ratio
  - Free Cash Flow Margin
"""

import warnings
from typing import Optional


# ---------------------------------------------------------------------------
# Data fetch helpers
# ---------------------------------------------------------------------------

def _row(df, *names):
    """Return first non-null value found across a list of row name aliases."""
    for name in names:
        if name in df.index:
            val = df.loc[name].dropna()
            if not val.empty:
                return val
    return None


def _val(series, col=0):
    """Safely get a scalar from a series at position col (current or prior year)."""
    try:
        if series is None or series.empty:
            return None
        return float(series.iloc[col])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Altman Z'-Score  (revised non-manufacturing version)
# Z' = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4
# ---------------------------------------------------------------------------

ALTMAN_SAFE     = 2.6
ALTMAN_DISTRESS = 1.1

def compute_altman(bs, inc) -> dict:
    """
    Returns:
        z_score: float or None
        zone:    'Safe' | 'Grey' | 'Distress' | 'Unavailable'
        components: dict of X1-X4
    """
    try:
        total_assets    = _val(_row(bs, "Total Assets"))
        working_capital = _val(_row(bs, "Working Capital"))
        retained_earn   = _val(_row(bs, "Retained Earnings"))
        ebit            = _val(_row(inc, "EBIT", "Operating Income"))
        equity          = _val(_row(bs, "Common Stock Equity", "Stockholders Equity",
                                    "Total Equity Gross Minority Interest"))
        total_liab      = _val(_row(bs, "Total Liabilities Net Minority Interest"))

        if None in (total_assets, working_capital, retained_earn, ebit, equity, total_liab):
            return _unavailable()
        if total_assets == 0 or total_liab == 0:
            return _unavailable()

        x1 = working_capital / total_assets
        x2 = retained_earn   / total_assets
        x3 = ebit            / total_assets
        x4 = equity          / total_liab

        z = round(6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4, 3)

        if z > ALTMAN_SAFE:
            zone = "Safe"
        elif z > ALTMAN_DISTRESS:
            zone = "Grey"
        else:
            zone = "Distress"

        return {
            "z_score": z,
            "zone": zone,
            "x1": round(x1, 4),
            "x2": round(x2, 4),
            "x3": round(x3, 4),
            "x4": round(x4, 4),
        }
    except Exception:
        return _unavailable()


def _unavailable():
    return {"z_score": None, "zone": "Unavailable", "x1": None, "x2": None, "x3": None, "x4": None}


# ---------------------------------------------------------------------------
# Beneish M-Score  (8-variable model)
# M = −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI
#          + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI
# M > −1.78  →  probable manipulator
# M < −2.22  →  unlikely manipulator
# ---------------------------------------------------------------------------

BENEISH_MANIPULATOR = -1.78
BENEISH_SAFE        = -2.22

def compute_beneish(bs, inc, cf) -> dict:
    """
    Uses two consecutive periods (iloc[0] = current, iloc[1] = prior year).
    Variables that cannot be computed are set to their neutral value (1.0)
    and flagged in missing_vars.
    """
    try:
        missing = []

        # --- Revenue (current + prior) ---
        rev_s = _row(inc, "Total Revenue", "Operating Revenue")
        rev_t  = _val(rev_s, 0)
        rev_t1 = _val(rev_s, 1)
        if rev_t is None or rev_t1 is None or rev_t1 == 0:
            return _beneish_unavailable()

        # --- Gross Profit ---
        gp_s  = _row(inc, "Gross Profit")
        gp_t  = _val(gp_s, 0)
        gp_t1 = _val(gp_s, 1)

        # --- Total Assets ---
        ta_s  = _row(bs, "Total Assets")
        ta_t  = _val(ta_s, 0)
        ta_t1 = _val(ta_s, 1)

        # --- Receivables (for DSRI) ---
        rec_s  = _row(bs, "Receivables", "Net Receivables", "Accounts Receivable")
        rec_t  = _val(rec_s, 0)
        rec_t1 = _val(rec_s, 1)

        # --- Current Assets ---
        ca_s  = _row(bs, "Current Assets")
        ca_t  = _val(ca_s, 0)
        ca_t1 = _val(ca_s, 1)

        # --- PP&E (for AQI, DEPI) ---
        ppe_s  = _row(bs, "Net PPE", "Properties", "Land And Improvements",
                      "Machinery Furniture Equipment")
        ppe_t  = _val(ppe_s, 0)
        ppe_t1 = _val(ppe_s, 1)

        # --- Depreciation ---
        dep_s  = _row(cf, "Depreciation And Amortization", "Depreciation",
                      "Depreciation Amortization Depletion")
        dep_t  = _val(dep_s, 0)
        dep_t1 = _val(dep_s, 1)

        # --- SGA ---
        sga_s  = _row(inc, "General And Administrative Expense",
                      "Selling General And Administration")
        sga_t  = _val(sga_s, 0)
        sga_t1 = _val(sga_s, 1)

        # --- Liabilities for LVGI ---
        ltd_s  = _row(bs, "Long Term Debt", "Long Term Debt And Capital Lease Obligation")
        ltd_t  = _val(ltd_s, 0)
        ltd_t1 = _val(ltd_s, 1)
        cl_s   = _row(bs, "Current Liabilities")
        cl_t   = _val(cl_s, 0)
        cl_t1  = _val(cl_s, 1)

        # --- Net Income + Operating Cash Flow for TATA ---
        ni_s  = _row(inc, "Net Income", "Net Income Common Stockholders")
        ni_t  = _val(ni_s, 0)
        ocf_s = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
        ocf_t = _val(ocf_s, 0)

        # --- Compute each variable ---

        # DSRI: Days Sales Receivable Index
        if rec_t is not None and rec_t1 is not None and rec_t1 != 0 and rev_t1 != 0:
            dsri = (rec_t / rev_t) / (rec_t1 / rev_t1)
        else:
            dsri = 1.0
            missing.append("DSRI")

        # GMI: Gross Margin Index
        if gp_t is not None and gp_t1 is not None and rev_t != 0 and rev_t1 != 0:
            gm_t  = gp_t  / rev_t
            gm_t1 = gp_t1 / rev_t1
            gmi = (gm_t1 / gm_t) if gm_t != 0 else 1.0
        else:
            gmi = 1.0
            missing.append("GMI")

        # AQI: Asset Quality Index
        if (ca_t is not None and ca_t1 is not None and
                ppe_t is not None and ppe_t1 is not None and
                ta_t is not None and ta_t1 is not None and
                ta_t != 0 and ta_t1 != 0):
            aq_t  = 1 - (ca_t  + ppe_t)  / ta_t
            aq_t1 = 1 - (ca_t1 + ppe_t1) / ta_t1
            aqi = (aq_t / aq_t1) if aq_t1 != 0 else 1.0
        else:
            aqi = 1.0
            missing.append("AQI")

        # SGI: Sales Growth Index
        sgi = rev_t / rev_t1 if rev_t1 != 0 else 1.0

        # DEPI: Depreciation Index
        if (dep_t is not None and dep_t1 is not None and
                ppe_t is not None and ppe_t1 is not None):
            d_rate_t  = dep_t  / (ppe_t  + dep_t)  if (ppe_t  + dep_t)  != 0 else None
            d_rate_t1 = dep_t1 / (ppe_t1 + dep_t1) if (ppe_t1 + dep_t1) != 0 else None
            depi = (d_rate_t1 / d_rate_t) if (d_rate_t and d_rate_t != 0) else 1.0
        else:
            depi = 1.0
            missing.append("DEPI")

        # SGAI: SGA Index
        if sga_t is not None and sga_t1 is not None and rev_t != 0 and rev_t1 != 0:
            sgai = (sga_t / rev_t) / (sga_t1 / rev_t1) if (sga_t1 / rev_t1) != 0 else 1.0
        else:
            sgai = 1.0
            missing.append("SGAI")

        # TATA: Total Accruals to Total Assets
        if ni_t is not None and ocf_t is not None and ta_t and ta_t != 0:
            tata = (ni_t - ocf_t) / ta_t
        else:
            tata = 0.0
            missing.append("TATA")

        # LVGI: Leverage Index
        if (ltd_t is not None and ltd_t1 is not None and
                cl_t is not None and cl_t1 is not None and
                ta_t is not None and ta_t1 is not None and
                ta_t != 0 and ta_t1 != 0):
            lev_t  = (ltd_t  + cl_t)  / ta_t
            lev_t1 = (ltd_t1 + cl_t1) / ta_t1
            lvgi = (lev_t / lev_t1) if lev_t1 != 0 else 1.0
        else:
            lvgi = 1.0
            missing.append("LVGI")

        m = (-4.840
             + 0.920  * dsri
             + 0.528  * gmi
             + 0.404  * aqi
             + 0.892  * sgi
             + 0.115  * depi
             - 0.172  * sgai
             + 4.679  * tata
             - 0.327  * lvgi)

        m = round(m, 3)

        if m > BENEISH_MANIPULATOR:
            flag = "Likely Manipulator"
        elif m > BENEISH_SAFE:
            flag = "Grey Zone"
        else:
            flag = "Low Manipulation Risk"

        return {
            "m_score": m,
            "flag": flag,
            "dsri": round(dsri, 3),
            "gmi":  round(gmi, 3),
            "sgi":  round(sgi, 3),
            "tata": round(tata, 4),
            "lvgi": round(lvgi, 3),
            "missing_vars": missing,
        }
    except Exception:
        return _beneish_unavailable()


def _beneish_unavailable():
    return {"m_score": None, "flag": "Unavailable", "dsri": None, "gmi": None,
            "sgi": None, "tata": None, "lvgi": None, "missing_vars": []}


# ---------------------------------------------------------------------------
# Interest Coverage Ratio  (EBIT / Interest Expense)
# ---------------------------------------------------------------------------

def compute_interest_coverage(inc) -> dict:
    try:
        ebit_s = _row(inc, "EBIT", "Operating Income")
        ebit   = _val(ebit_s, 0)

        int_s  = _row(inc, "Interest Expense Non Operating", "Interest Expense",
                      "Net Interest Income")
        int_exp = _val(int_s, 0)

        if ebit is None or int_exp is None or int_exp == 0:
            return {"icr": None, "icr_label": "Unavailable"}

        # Interest expense is typically reported as negative; take absolute value
        int_exp = abs(int_exp)
        icr = round(ebit / int_exp, 2)

        if icr < 1.0:
            label = "Critical — cannot cover interest"
        elif icr < 1.5:
            label = "Danger — barely covering interest"
        elif icr < 3.0:
            label = "Weak coverage"
        elif icr < 5.0:
            label = "Adequate coverage"
        else:
            label = "Strong coverage"

        return {"icr": icr, "icr_label": label}
    except Exception:
        return {"icr": None, "icr_label": "Unavailable"}


# ---------------------------------------------------------------------------
# Free Cash Flow Margin
# ---------------------------------------------------------------------------

def compute_fcf_margin(inc, cf) -> Optional[float]:
    try:
        fcf_s = _row(cf, "Free Cash Flow")
        fcf   = _val(fcf_s, 0)
        rev_s = _row(inc, "Total Revenue", "Operating Revenue")
        rev   = _val(rev_s, 0)
        if fcf is None or rev is None or rev == 0:
            return None
        return round((fcf / rev) * 100, 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Master function: compute all advanced scores from yfinance ticker
# ---------------------------------------------------------------------------

def compute_all_advanced(ticker_obj) -> dict:
    # Use the retry helper from ingestion.py so the same back-off
    # behaviour applies here too — wraps yfinance properties so a transient
    # Yahoo rate-limit becomes a graceful empty-frame instead of a crash.
    from backend.services.ingestion import _safe_yf
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bs  = _safe_yf(lambda: ticker_obj.balance_sheet)
            inc = _safe_yf(lambda: ticker_obj.financials)
            cf  = _safe_yf(lambda: ticker_obj.cashflow)

        altman   = compute_altman(bs, inc)
        beneish  = compute_beneish(bs, inc, cf)
        icr      = compute_interest_coverage(inc)
        fcf_margin = compute_fcf_margin(inc, cf)

        return {
            "altman": altman,
            "beneish": beneish,
            "icr": icr["icr"],
            "icr_label": icr["icr_label"],
            "fcf_margin": fcf_margin,
        }
    except Exception:
        return {
            "altman": _unavailable(),
            "beneish": _beneish_unavailable(),
            "icr": None,
            "icr_label": "Unavailable",
            "fcf_margin": None,
        }
