"""
Redis caching layer with graceful degradation.

If Redis is unreachable the cache silently no-ops: analysis still works, it
just re-fetches from yfinance every time. A failed connection or operation
puts the cache into a short cooldown, so a down Redis never adds connection
latency to every request.
"""

import json
import logging
import time
from typing import Any, Optional

import redis

from backend.config import settings

log = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None
_cooldown_until: float = 0.0
_COOLDOWN_SECONDS = 60


def _client_or_none() -> Optional[redis.Redis]:
    """Return a live Redis client, or None if Redis is down / in cooldown."""
    global _client, _cooldown_until
    if time.time() < _cooldown_until:
        return None
    if _client is not None:
        return _client
    try:
        c = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        c.ping()
        _client = c
        return c
    except Exception as e:
        log.warning("Redis unavailable (%s) — caching disabled for %ds",
                    e, _COOLDOWN_SECONDS)
        _cooldown_until = time.time() + _COOLDOWN_SECONDS
        return None


def _json_default(o):
    """
    Coerce values json.dumps cannot handle natively — notably numpy scalars,
    which yfinance-derived fields can be — so a cache write never silently
    fails (and trips the cooldown) over a stray numpy.int64.
    """
    if hasattr(o, "item"):          # numpy int64/float64 and similar
        return o.item()
    raise TypeError(f"not JSON-serialisable: {type(o).__name__}")


def _trip_cooldown(exc: Exception) -> None:
    global _client, _cooldown_until
    log.warning("Redis operation failed (%s) — caching disabled for %ds",
                exc, _COOLDOWN_SECONDS)
    _client = None
    _cooldown_until = time.time() + _COOLDOWN_SECONDS


def cache_get(key: str) -> Optional[Any]:
    """Return the cached JSON value for key, or None on miss / Redis down."""
    client = _client_or_none()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as e:
        _trip_cooldown(e)
        return None


def cache_set(key: str, value: Any, ttl: int) -> None:
    """Store value (JSON-encoded) under key with a TTL. No-op if Redis down."""
    client = _client_or_none()
    if client is None:
        return
    try:
        client.set(key, json.dumps(value, default=_json_default), ex=ttl)
    except Exception as e:
        _trip_cooldown(e)


def cache_healthy() -> bool:
    """True if Redis is currently reachable."""
    return _client_or_none() is not None
