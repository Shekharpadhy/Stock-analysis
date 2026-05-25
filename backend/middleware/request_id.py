"""
Request-correlation middleware.

What this gives us
──────────────────
Every incoming HTTP request gets a UUID, propagated through three places:

  1. A `ContextVar` so any code inside the request handler can grab the
     active ID without it having to be passed around explicitly.
  2. The `X-Request-ID` response header — the client (browser, API consumer)
     can quote it back when reporting an error.
  3. Every log line emitted during the request — JsonFormatter sees the
     `request_id` attribute on the LogRecord and includes it in the JSON.

Inbound `X-Request-ID` headers are honoured when present (sane format),
otherwise we generate a fresh UUID.  Honouring inbound IDs lets you trace
across the reverse proxy / upstream services that already emit them.

Implementation note
───────────────────
We attach the ID to the LogRecord via a logging.Filter — that way it shows
up automatically in every log line, not just those where the developer
remembered to pass `extra={"request_id": ...}`.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Active request ID, accessible from anywhere in the request lifecycle.
_request_id: ContextVar[Optional[str]] = ContextVar("bcsi.request_id", default=None)


def get_request_id() -> Optional[str]:
    """Return the active request ID, or None outside a request."""
    return _request_id.get()


# Accept reasonable client-supplied IDs (UUID-ish), reject anything weird so
# we don't end up logging attacker-controlled payloads under that key.
_INBOUND_ID_RE = re.compile(r"^[A-Za-z0-9._-]{6,128}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Sets the request ID for the duration of every request."""

    HEADER = "X-Request-ID"

    async def dispatch(self, request: Request, call_next):
        inbound = request.headers.get(self.HEADER, "")
        if inbound and _INBOUND_ID_RE.match(inbound):
            rid = inbound
        else:
            rid = str(uuid.uuid4())

        token = _request_id.set(rid)
        try:
            response: Response = await call_next(request)
        finally:
            _request_id.reset(token)

        response.headers[self.HEADER] = rid
        return response


class RequestIDLogFilter(logging.Filter):
    """
    logging.Filter that attaches the active request_id to every LogRecord.

    Installed once at logging configuration time — JsonFormatter then picks
    it up via its existing "extra fields" pass.  Records emitted outside a
    request get `request_id="-"` so the key is always present.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get() or "-"
        return True
