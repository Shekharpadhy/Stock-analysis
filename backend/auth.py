"""
JWT authentication.

A single admin credential (configured via env: ADMIN_USERNAME / ADMIN_PASSWORD)
is exchanged at POST /api/v1/auth/token for a short-lived bearer JWT. Protected
routes depend on require_auth, which validates the
``Authorization: Bearer <token>`` header.

For multi-user support later, replace the single-credential check in
authenticate_admin() with a lookup against a hashed-password users table —
the require_auth dependency and token format stay the same.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from backend.config import settings

log = logging.getLogger(__name__)

_INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me"
if settings.jwt_secret == _INSECURE_DEFAULT_SECRET:
    log.warning(
        "JWT_SECRET is the insecure default — set a strong random secret "
        "via the JWT_SECRET env var before deploying."
    )

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def authenticate_admin(username: str, password: str) -> bool:
    """Constant-time check of supplied credentials against the configured admin."""
    user_ok = secrets.compare_digest(username, settings.admin_username)
    pass_ok = secrets.compare_digest(password, settings.admin_password)
    return user_ok and pass_ok


def create_access_token(subject: str) -> str:
    """Issue a signed JWT for the given subject, expiring per settings."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def require_auth(token: str = Depends(oauth2_scheme)) -> str:
    """
    FastAPI dependency — validate the bearer token and return its subject.
    Raises 401 on a missing, malformed, expired, or wrongly-signed token.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        raise credentials_error

    subject = payload.get("sub")
    if not subject:
        raise credentials_error
    return subject
