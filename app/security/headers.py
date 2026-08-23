"""Security response headers and Host-header validation."""

from __future__ import annotations

from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "  # inline bootstrap scripts + tojson data
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline hardening headers to every HTTP response.

    HSTS is opt-in (``INFRAMP_HSTS_ENABLED``) because TLS is expected to
    terminate at a reverse proxy, not in-app.
    """

    def __init__(self, app, hsts_enabled: bool = False):
        super().__init__(app)
        self._hsts = hsts_enabled

    async def dispatch(self, request: Request, call_next: Callable):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", CSP_POLICY)
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
