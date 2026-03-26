# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

**Do not** open a public GitHub issue for security vulnerabilities.

Please email the maintainers directly. We aim to acknowledge reports within 48 hours
and will coordinate a fix and responsible disclosure timeline with you.

## Security Practices in This Project

- All API endpoints require JWT Bearer authentication (except `/health`)
- Passwords are never stored — only short-lived access tokens and hashed refresh tokens
- Rate limiting (SlowAPI) is enforced on all public-facing routes
- Database credentials and secrets are loaded from environment variables only
- `.env` files are excluded from version control via `.gitignore`
- Dependencies are pinned in `requirements.txt` and audited in CI
