# Security Policy

## Supported Versions

| Version | Status      |
|---------|-------------|
| 1.0.x   | Supported   |
| 0.5.x   | Critical fixes only (until 2026-Q4) |
| < 0.5   | End of life |

## Reporting a Vulnerability

**Do not** open a public GitHub issue for security vulnerabilities.

Email the maintainers directly. We aim to acknowledge reports within 48 hours
and will coordinate a fix and responsible disclosure timeline with you. Please
include:

- A description of the issue and its impact
- Steps to reproduce (or a PoC)
- Affected version(s)
- Any mitigating factors you've already identified

We do not currently run a paid bug-bounty program but credit reporters in the
release notes when they consent.

---

## Security Controls in v1.0

### Authentication

- **Password hashing** — argon2id (OWASP-recommended) via passlib. Legacy
  sha256_crypt hashes from v0.2.x verify too, but get transparently upgraded
  to argon2id on the user's next successful login.
- **JWT bearer tokens** — HS256, short-lived (default 60 min). The decoder
  supports a `JWT_SECRET_PREVIOUS` fallback for zero-downtime key rotation;
  see DEPLOYMENT.md for the procedure.
- **Email verification** — required at registration. `email_verified` is
  surfaced in `/users/me`; downstream features can gate on it.
- **Password reset** — single-use tokens (SHA-256 hashed in the DB, plaintext
  never persisted), 1-hour TTL, request a new one invalidates the prior.
- **Auth rate limits** — slowapi caps `/auth/login`, `/auth/register`,
  `/auth/password-reset/*`, `/auth/verify`. Defaults: 10/min login, 5/hr
  register, 3/hr reset.
- **Account enumeration resistance** — `/auth/password-reset/request` and
  `/auth/verify/resend` return 202 unconditionally, regardless of whether
  the email matches an account.

### Authorization

- Admin-only routes guarded by `require_admin_auth` (checks `role == "admin"`
  in the JWT claims). Returns 403 for authenticated non-admin tokens.
- User-scoped routes (`/users/me/*`) enforce per-user isolation in the query
  itself — cross-user access by ID returns 404, never 403, so the existence
  of another user's records is not leaked.

### Transport + storage

- Passwords are never logged, returned, or stored in plaintext.
- `JWT_SECRET` and `ADMIN_PASSWORD` are required to be non-default when
  `APP_ENV=production` — the app refuses to start otherwise.
- All secrets loaded from environment variables; `.env` files are
  `.gitignore`-d.
- DB connection uses parameterised queries throughout (SQLAlchemy ORM);
  no raw string-interpolation.

### Operational

- Per-IP rate limiting (slowapi) on all public routes, tighter limits on
  auth endpoints.
- CORS allowlist enforced via `CORS_ORIGINS` env var — no `"*"` in default
  production config.
- **Audit log** records every privileged action (admin login, ML retrain,
  scheduler run, user registration, password reset, email verification).
  Append-only, indexed by actor / action / target / timestamp.
- **Request ID** middleware stamps every request with a UUID, echoed in the
  `X-Request-ID` response header and embedded in every log line — turns
  cross-service incident triage into a one-line grep.

### Background processing

- **Scheduler leader election** via DB-backed lease (`scheduler_lock` table)
  so multiple workers can run with `SCHEDULER_ENABLED=true` without
  double-firing jobs. Exactly one worker holds the lock at a time;
  failed-over workers reclaim within `LEASE_SECONDS` (90s default).
- Background jobs catch their own exceptions and return structured
  summaries — a poisoned job never takes down the scheduler.

### Dependencies + supply chain

- `requirements.txt` pins exact versions of every runtime dependency.
- CI runs the full test suite + coverage gate (`--cov-fail-under=78`) on
  every PR.
- Optional `ruff` lint job (advisory; not gating).

---

## Out of scope for v1.0 (planned)

- **MFA / TOTP** — second factor on login. Currently password-only.
- **Session revocation** before token expiry. Today, tokens are valid until
  their `exp` claim or until `JWT_SECRET` is rotated.
- **CSP / security headers** beyond the defaults Starlette emits. A CSP
  policy will land alongside the marketing site.
- **Penetration test report** — internal-only review for v1.0; external pen
  test scheduled for v1.1.
