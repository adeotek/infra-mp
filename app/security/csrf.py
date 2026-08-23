"""CSRF protection: HMAC tokens bound to the session cookie.

The token is derived from the server-side secret key and the *value* of the
session cookie (a 256-bit random token known only to the client), so an
attacker who cannot read the victim's cookie cannot forge a token — this is
the signed double-submit pattern. Pre-login requests have no session cookie;
``/login`` itself is exempt (no state change worth forging without a session).

Implementation note: the middleware is plain ASGI (not ``BaseHTTPMiddleware``)
because reading the form body in a base middleware drains the receive stream
and FastAPI's downstream ``Form(...)`` parsing would see an empty body. Here
the body is buffered once and replayed to the app through a wrapped receive
channel. Requests carrying a valid ``X-CSRF-Token`` header (HTMX and fetch
calls) are passed straight through without touching the body.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Endpoints authenticated by API token (MCP) or with no session yet.
EXEMPT_PREFIXES = ("/mcp", "/static", "/login")

# Reused when the operator left the documented default key in place: the
# session cookie still provides the secrecy, the key only acts as a pepper.
_DEFAULT_KEYS = {"", "change-me-in-production", "change-me-to-a-long-random-string"}

_ephemeral_key: str | None = None

_MULTIPART_FIELD = re.compile(rb'name="csrf_token"\r\n\r\n([^\r\n]+)')


def _signing_key(secret_key: str) -> bytes:
    """The HMAC key, falling back to a boot-random key when unconfigured."""
    if secret_key not in _DEFAULT_KEYS:
        return secret_key.encode("utf-8")
    global _ephemeral_key
    if _ephemeral_key is None:
        _ephemeral_key = secrets.token_hex(32)
        logger.warning(
            "INFRAMP_SECRET_KEY is unset or left at its default; CSRF tokens are "
            "signed with an ephemeral boot-random key. Set INFRAMP_SECRET_KEY to a "
            "long random string to keep tokens stable across restarts."
        )
    return _ephemeral_key.encode("utf-8")


def _request_settings(request: Request):
    """The settings bound to this request's app (falls back to the global)."""
    state = getattr(getattr(request, "app", None), "state", None)
    settings = getattr(state, "settings", None) if state is not None else None
    if settings is not None:
        return settings
    from app.config import get_settings

    return get_settings()


def csrf_token_for(request: Request) -> str:
    """The CSRF token to embed in forms served to this request."""
    settings = _request_settings(request)
    session_value = request.cookies.get(settings.session_cookie_name, "") or ""
    digest = hmac.new(
        _signing_key(settings.secret_key),
        session_value.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:43]


def _form_field(body: bytes, content_type: str, field: str) -> str | None:
    """Extract one form field from a raw request body (urlencoded or multipart)."""
    media_type = (content_type or "").split(";")[0].strip().lower()
    if media_type == "application/x-www-form-urlencoded":
        values = parse_qs(body.decode("utf-8", errors="ignore")).get(field, [])
        return values[-1] if values else None
    if media_type == "multipart/form-data":
        # The token is a single-line base64url value, so a targeted scan over
        # the raw multipart body is unambiguous.
        match = _MULTIPART_FIELD.search(body)
        if match:
            return match.group(1).decode("utf-8", errors="ignore")
    return None


class CSRFMiddleware:
    """Reject unsafe requests that do not carry a valid CSRF token.

    The token is accepted as the ``X-CSRF-Token`` header (HTMX and ``fetch``
    calls) or as a ``csrf_token`` form field (plain HTML forms, including the
    no-JS path). ``/mcp`` is authenticated by API token and ``/login`` has no
    session yet, so both are exempt.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        if request.method in SAFE_METHODS or request.url.path.startswith(EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        expected = csrf_token_for(request)
        header = request.headers.get("X-CSRF-Token") or ""
        if header and hmac.compare_digest(header, expected):
            await self.app(scope, receive, send)
            return

        # No (valid) header: buffer the body, check the form field, and replay
        # the buffered body downstream so FastAPI can parse the form again.
        body = bytearray()
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                more = message.get("more_body", False)
            else:
                more = False

        submitted = _form_field(bytes(body), request.headers.get("content-type", ""), "csrf_token")
        if submitted and hmac.compare_digest(submitted, expected):
            replayed = False

            async def replay_receive():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay_receive, send)
            return

        response = JSONResponse(
            status_code=403,
            content={"detail": "CSRF validation failed. Reload the page and retry."},
        )
        await response(scope, receive, send)
