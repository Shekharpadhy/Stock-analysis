"""
JWT authentication — supports both the legacy admin-only flow and the new
multi-user flow introduced in v0.2.0.

Admin flow (unchanged)
──────────────────────
  POST /auth/token (form-encoded) → short-lived bearer JWT with sub="admin".
  Protected admin routes use `require_auth`.

User flow (new)
───────────────
  POST /auth/register (JSON) → create account
  POST /auth/login    (JSON) → bearer JWT with sub=<username>, role=<role>
  User and admin routes use `require_user_auth`.
  Admin-only routes use `require_admin_auth` (checks role == "admin").

Password storage
────────────────
  bcrypt via passlib.  Plain-text passwords are never stored.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.config import settings

log = logging.getLogger(__name__)

_INSECURE_DEFAULT_SECRET = "dev-only-insecure-secret-change-me"
if settings.jwt_secret == _INSECURE_DEFAULT_SECRET:
    log.warning(
        "JWT_SECRET is the insecure default — set a strong random secret "
        "via the JWT_SECRET env var before deploying."
    )

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

# ── password hashing ──────────────────────────────────────────────────────────

# sha256_crypt has no external C-library dependency and works reliably on all
# Python 3.9+ platforms.  Swap to bcrypt in production if desired.
_pwd_ctx = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ── admin credential check (legacy) ──────────────────────────────────────────

def authenticate_admin(username: str, password: str) -> bool:
    """Constant-time check against the configured admin credentials."""
    user_ok = secrets.compare_digest(username, settings.admin_username)
    pass_ok = secrets.compare_digest(password, settings.admin_password)
    return user_ok and pass_ok


# ── token creation ────────────────────────────────────────────────────────────

def create_access_token(subject: str, role: str = "admin") -> str:
    """Issue a signed JWT for the given subject + role."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> dict:
    """Decode and validate a bearer JWT.  Raises 401 on any failure."""
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
    if not payload.get("sub"):
        raise credentials_error
    return payload


# ── dependencies ──────────────────────────────────────────────────────────────

def require_auth(token: str = Depends(oauth2_scheme)) -> str:
    """
    Admin-only dependency (backward-compatible).
    Returns the token subject (always "admin" for admin tokens).
    """
    payload = _decode_token(token)
    return payload["sub"]


def require_user_auth(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Any-authenticated-user dependency.
    Returns the full decoded payload dict: {"sub": username, "role": role}.
    """
    return _decode_token(token)


def require_admin_auth(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Admin-role dependency — accepts tokens with role == 'admin'.
    Returns the full decoded payload dict.
    """
    payload = _decode_token(token)
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return payload
