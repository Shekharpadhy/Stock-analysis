"""
Email / Slack alert engine.

Architecture
────────────
AlertSubscription — a DB row that says "email X (or Slack) when ticker Y
crosses threshold Z on metric M".

Delivery channels
─────────────────
  • SMTP email via smtplib (TLS, configurable host/port/credentials)
  • Slack incoming webhook via httpx

Trigger helpers
───────────────
  check_and_fire(ticker, old_record, new_record, db)
      Called by the ingestion / analyse pipeline whenever a CompanyRecord
      is updated.  Finds all subscriptions for that ticker, evaluates
      each rule, and fires alerts when the condition becomes true
      (edge-triggered: only fires on the *transition*, not every poll).

  fire_test_alert(subscription, db)
      Sends an unconditional test alert for a given subscription.

Supported alert conditions
──────────────────────────
  risk_score_above   – risk_score crosses above threshold
  distress_zone      – altman_zone becomes "Distress"
  ml_prob_above      – ML distress probability crosses above threshold
  quality_score_below – quality_score drops below threshold
"""

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

import httpx

from backend.config import settings

log = logging.getLogger(__name__)

# ── condition registry ────────────────────────────────────────────────────────

VALID_CONDITIONS = {
    "risk_score_above",
    "distress_zone",
    "ml_prob_above",
    "quality_score_below",
}

# ── payload builder ───────────────────────────────────────────────────────────

def _build_alert_payload(
    ticker: str,
    condition: str,
    threshold: Optional[float],
    current_value,
    extra: Optional[Dict] = None,
) -> Dict:
    """Return a structured alert payload dict (used for both email and Slack)."""
    thr_fmt = f"{threshold:.0f}" if threshold is not None else "N/A"
    thr_pct = f"{threshold:.0%}" if threshold is not None else "N/A"
    labels = {
        "risk_score_above":    f"Risk score above {thr_fmt}",
        "distress_zone":       "Altman Z-score zone changed to Distress",
        "ml_prob_above":       f"ML distress probability above {thr_pct}",
        "quality_score_below": f"Quality score below {thr_fmt}",
    }
    return {
        "ticker":        ticker,
        "condition":     condition,
        "threshold":     threshold,
        "current_value": current_value,
        "headline":      f"⚠️  BCSI Alert — {ticker}: {labels.get(condition, condition)}",
        "extra":         extra or {},
    }


# ── email delivery ────────────────────────────────────────────────────────────

def _send_email(to_address: str, payload: Dict) -> bool:
    """
    Send an HTML+plain alert email.
    Returns True on success, False on any error.
    """
    if not settings.alert_smtp_host or not settings.alert_smtp_user:
        log.debug("alerts: SMTP not configured — skipping email to %s", to_address)
        return False

    subject = payload["headline"]
    body_plain = (
        f"{payload['headline']}\n\n"
        f"Ticker:    {payload['ticker']}\n"
        f"Condition: {payload['condition']}\n"
        f"Value:     {payload['current_value']}\n"
        f"Threshold: {payload['threshold']}\n"
    )
    body_html = f"""
<html><body style="font-family:sans-serif;background:#0d1117;color:#e6edf3;padding:24px">
  <h2 style="color:#f85149">{payload["headline"]}</h2>
  <table style="border-collapse:collapse">
    <tr><td style="padding:6px 16px 6px 0;color:#7d8590">Ticker</td>
        <td style="font-weight:700">{payload["ticker"]}</td></tr>
    <tr><td style="padding:6px 16px 6px 0;color:#7d8590">Condition</td>
        <td>{payload["condition"]}</td></tr>
    <tr><td style="padding:6px 16px 6px 0;color:#7d8590">Current value</td>
        <td><b>{payload["current_value"]}</b></td></tr>
    <tr><td style="padding:6px 16px 6px 0;color:#7d8590">Threshold</td>
        <td>{payload["threshold"]}</td></tr>
  </table>
  <p style="margin-top:24px;font-size:12px;color:#7d8590">
    Banking Client Sector Intelligence — automated alert
  </p>
</body></html>
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.alert_email_from
    msg["To"]      = to_address
    msg.attach(MIMEText(body_plain, "plain"))
    msg.attach(MIMEText(body_html,  "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.alert_smtp_host, settings.alert_smtp_port) as srv:
            srv.ehlo()
            srv.starttls(context=ctx)
            srv.login(settings.alert_smtp_user, settings.alert_smtp_password)
            srv.sendmail(settings.alert_email_from, to_address, msg.as_string())
        log.info("alerts: email sent to %s [%s / %s]",
                 to_address, payload["ticker"], payload["condition"])
        return True
    except Exception as exc:
        log.warning("alerts: email failed to %s — %s", to_address, exc)
        return False


# ── Slack delivery ────────────────────────────────────────────────────────────

def _send_slack(webhook_url: str, payload: Dict) -> bool:
    """
    Post a Block Kit message to a Slack incoming webhook.
    Returns True on success.
    """
    if not webhook_url:
        log.debug("alerts: Slack webhook not configured")
        return False

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": payload["headline"], "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Ticker*\n{payload['ticker']}"},
                {"type": "mrkdwn", "text": f"*Condition*\n{payload['condition']}"},
                {"type": "mrkdwn", "text": f"*Current value*\n{payload['current_value']}"},
                {"type": "mrkdwn", "text": f"*Threshold*\n{payload['threshold']}"},
            ],
        },
        {"type": "divider"},
    ]

    try:
        resp = httpx.post(webhook_url, json={"blocks": blocks}, timeout=10)
        resp.raise_for_status()
        log.info("alerts: Slack sent [%s / %s]", payload["ticker"], payload["condition"])
        return True
    except Exception as exc:
        log.warning("alerts: Slack failed — %s", exc)
        return False


# ── dispatch helper ───────────────────────────────────────────────────────────

def dispatch(sub, payload: Dict) -> Dict:
    """
    Deliver one alert via all channels registered on `sub`.
    Returns {"email": bool, "slack": bool}.
    """
    result: Dict = {}

    if sub.email:
        result["email"] = _send_email(sub.email, payload)

    slack_url = sub.slack_webhook or settings.alert_slack_webhook
    if slack_url:
        result["slack"] = _send_slack(slack_url, payload)

    return result


# ── condition evaluator ───────────────────────────────────────────────────────

def _evaluate_condition(
    condition: str,
    threshold: Optional[float],
    old_rec,
    new_rec,
    ml_prob: Optional[float] = None,
) -> tuple:
    """
    Return (triggered: bool, current_value).
    Edge-triggered: only True when crossing FROM false TO true.
    """
    def _val(rec, attr):
        return getattr(rec, attr, None)

    if condition == "risk_score_above":
        thr  = threshold if threshold is not None else settings.alert_risk_threshold
        old  = _val(old_rec, "risk_score") or 0.0
        new  = _val(new_rec, "risk_score") or 0.0
        return (old <= thr < new or (old is None and new > thr)), round(new, 1)

    if condition == "distress_zone":
        old_zone = _val(old_rec, "altman_zone")
        new_zone = _val(new_rec, "altman_zone")
        return (new_zone == "Distress" and old_zone != "Distress"), new_zone

    if condition == "ml_prob_above":
        thr = threshold if threshold is not None else 0.60
        if ml_prob is None:
            return False, None
        old_prob = getattr(old_rec, "_last_ml_prob", 0.0) or 0.0
        return (old_prob <= thr < ml_prob), round(ml_prob, 4)

    if condition == "quality_score_below":
        thr = threshold if threshold is not None else 40.0
        old  = _val(old_rec, "quality_score")
        new  = _val(new_rec, "quality_score")
        if old is None or new is None:
            return False, new
        return (old >= thr > new), round(new, 1)

    return False, None


# ── public trigger API ────────────────────────────────────────────────────────

def check_and_fire(
    ticker: str,
    old_rec,
    new_rec,
    db,
    ml_prob: Optional[float] = None,
) -> List[Dict]:
    """
    Evaluate every active AlertSubscription for `ticker`.
    Fire alerts for conditions that just became true (edge-triggered).
    Returns list of fired alert result dicts.
    """
    from backend.database.db import AlertSubscription   # lazy

    subs = (
        db.query(AlertSubscription)
        .filter(
            AlertSubscription.ticker == ticker,
            AlertSubscription.active.is_(True),
        )
        .all()
    )

    fired = []
    for sub in subs:
        triggered, current_value = _evaluate_condition(
            sub.condition, sub.threshold, old_rec, new_rec, ml_prob
        )
        if not triggered:
            continue

        payload = _build_alert_payload(
            ticker, sub.condition, sub.threshold, current_value
        )
        delivery = dispatch(sub, payload)
        fired.append({"subscription_id": sub.id, "payload": payload,
                      "delivery": delivery})
        log.info("alerts: fired %s for %s (sub=%s)", sub.condition, ticker, sub.id)

    return fired


def fire_test_alert(sub, ticker: str) -> Dict:
    """
    Send an unconditional test alert for the given subscription.
    Used by POST /alerts/test.
    """
    payload = _build_alert_payload(
        ticker, sub.condition, sub.threshold,
        current_value="[test]",
        extra={"test": True},
    )
    payload["headline"] = "🧪 TEST — " + payload["headline"]
    delivery = dispatch(sub, payload)
    return {"payload": payload, "delivery": delivery}


# ── config introspection ──────────────────────────────────────────────────────

def get_config() -> Dict:
    """Return sanitised alert channel configuration (no secrets)."""
    return {
        "smtp_configured":    bool(settings.alert_smtp_host and settings.alert_smtp_user),
        "slack_configured":   bool(settings.alert_slack_webhook),
        "smtp_host":          settings.alert_smtp_host or None,
        "smtp_port":          settings.alert_smtp_port,
        "email_from":         settings.alert_email_from,
        "default_risk_threshold": settings.alert_risk_threshold,
        "valid_conditions":   sorted(VALID_CONDITIONS),
    }
