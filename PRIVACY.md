# Privacy Notice — Operator Reference

This document explains what personal data the Banking Client Sector
Intelligence platform stores, why, and how an operator can fulfil data
subject requests. It is **not** the user-facing privacy policy your
business publishes — that needs your jurisdiction's specific language —
but it is the authoritative system reference your privacy policy should be
based on.

---

## Data stored about a registered user

| Field                | Where             | Purpose                                                              |
|----------------------|-------------------|----------------------------------------------------------------------|
| `username`           | `users`           | Identity + URL slugs                                                  |
| `email`              | `users`           | Login, account-lifecycle email (verification, password reset)        |
| `hashed_password`    | `users`           | Authentication — argon2id; original password never stored             |
| `role`               | `users`           | Authorization (`user` / `admin`)                                      |
| `is_active`          | `users`           | Soft-delete / disable flag                                            |
| `email_verified`     | `users`           | Whether the address was confirmed                                     |
| `created_at`         | `users`           | Account age, for support / debugging                                  |
| Watchlist tickers    | `watchlist`       | The user's curated list (with optional `notes`)                      |
| Alert subscriptions  | `alert_subscriptions` | Per-user alert configuration                                      |
| Audit log entries    | `audit_log`       | Records of privileged actions the user took (login, password change) |

We do **not** store:

- The plaintext password (only the argon2id hash)
- IP addresses on a per-user basis — only as transient rate-limiter keys
- Browser fingerprints
- Names, addresses, phone numbers
- Financial data tied to the user (account numbers, balances, holdings)

The platform stores market data (`companies`, `price_history`,
`backtest_observations`, `predictions`, `sector_profiles`,
`governance_records`) — none of which is personal data.

---

## Email delivery

The platform sends three classes of email:

1. **Verification** — on registration. One message per signup.
2. **Password reset** — on `/auth/password-reset/request`. Rate-limited to
   3/hour per IP.
3. **Alerts** — only to users who explicitly subscribe or who add a ticker
   to their watchlist (which auto-creates conservative alerts for risk and
   distress signals).

Emails are sent via the operator's configured SMTP provider
(`ALERT_SMTP_HOST`, etc.). The platform does not retain a copy of the
message body, only the trigger record in `audit_log` /
`alert_subscriptions.last_fired_at`.

---

## Retention

The platform does **not** auto-rotate any of these tables. Operators
should define and enforce a retention policy appropriate to their
jurisdiction:

| Table                  | Suggested retention                     | Why                                                |
|------------------------|-----------------------------------------|----------------------------------------------------|
| `users`                | Active life of account + 30 days        | Account recovery window after deletion request     |
| `audit_log`            | 12 months minimum (compliance regimes vary) | Forensic / regulatory                            |
| `user_tokens`          | 30 days (cron can prune `used_at IS NOT NULL`) | Tokens are single-use; no need to keep forever |
| `alert_subscriptions`  | Until user removes or account deleted   | User-controlled                                    |
| `watchlist`            | Until user removes or account deleted   | User-controlled                                    |

A scheduled job to prune expired `user_tokens` is straightforward to add;
it isn't bundled today because retention policy is operator-specific.

---

## Fulfilling a data subject request

### Access (SAR)

Run, replacing `<USERNAME>`:

```sql
SELECT * FROM users        WHERE username = '<USERNAME>';
SELECT * FROM watchlist    WHERE user_id = (SELECT id FROM users WHERE username = '<USERNAME>');
SELECT * FROM alert_subscriptions WHERE user_id = (SELECT id FROM users WHERE username = '<USERNAME>');
SELECT * FROM audit_log    WHERE actor    = '<USERNAME>';
SELECT * FROM user_tokens  WHERE user_id  = (SELECT id FROM users WHERE username = '<USERNAME>');
```

Export the result set and provide to the user in their preferred format.

### Deletion (right to be forgotten)

The platform does not currently ship an `/auth/account/delete` endpoint —
deletions are operator-handled. The correct sequence is:

```sql
BEGIN;

-- 1. Soft-delete the user (preserves audit history).
UPDATE users
   SET is_active = FALSE,
       email     = 'deleted-' || id || '@example.invalid',
       hashed_password = 'deleted'
 WHERE username = '<USERNAME>';

-- 2. Remove the user's content.
DELETE FROM watchlist           WHERE user_id = (SELECT id FROM users WHERE username = '<USERNAME>');
DELETE FROM alert_subscriptions WHERE user_id = (SELECT id FROM users WHERE username = '<USERNAME>');
DELETE FROM user_tokens         WHERE user_id = (SELECT id FROM users WHERE username = '<USERNAME>');

-- 3. Leave audit_log INTACT — required for compliance review.  The user's
-- personal data is already redacted in step 1; only their actions remain.

COMMIT;
```

For full erasure including audit history, also `DELETE FROM audit_log
WHERE actor = '<USERNAME>'` — but check the regulatory regime first;
many require audit-log retention to override the right-to-erasure.

### Rectification

Username/email changes are not currently a user-facing flow; update the
`users` row directly and record the change in `audit_log`:

```sql
INSERT INTO audit_log (actor, action, target, extra, timestamp)
VALUES ('admin', 'user.email_change', '<USER_ID>',
        '{"old": "...", "new": "..."}', NOW());

UPDATE users SET email = '<NEW>' WHERE id = <USER_ID>;
```

### Restriction of processing

Set `is_active = FALSE`. The user can no longer log in; their watchlist
and alerts remain inert until reactivated.

---

## Sub-processors

The platform does not directly contract with any sub-processor — what it
sends out (via the operator-configured SMTP server and Slack webhook URL)
is configured per-deployment. Your privacy notice must enumerate whichever
of those you choose to use.

---

## Contact

For privacy questions about the platform itself (not data your operator
holds), email the project maintainers via the channel in `SECURITY.md`.
