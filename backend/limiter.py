"""
Shared per-IP rate limiter (slowapi).

Defined in its own module so both main.py (middleware + handler wiring) and
routes.py (tighter per-route limits) can import the same Limiter instance
without a circular import.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
)
