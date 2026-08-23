"""Application factory and entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.routing import Route

from app.auth.seed import seed_admin
from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory
from app.routes import api_tokens, auth, backup, dashboard, entities, records, users, views
from app.security.csrf import CSRFMiddleware
from app.security.headers import SecurityHeadersMiddleware
from app.security.ratelimit import LoginRateLimiter
from app.templates import is_htmx, render

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


async def _mcp_responds(app) -> bool:
    """Call the MCP app in-process and expect the auth middleware's 401.

    The request carries an invalid Bearer token: the SDK's authentication
    middleware runs the token verifier (which queries the database) and must
    answer ``401``. Any other outcome — an exception, a 5xx, a different
    status — means the MCP transport is not healthy. This is what
    ``/mcp/readyz`` probes.
    """
    status: dict = {}
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/mcp/",
        "root_path": "/mcp",
        "scheme": "http",
        "query_string": b"",
        "headers": [
            (b"host", b"localhost"),
            (b"content-type", b"application/json"),
            (b"authorization", b"Bearer probe-invalid-token"),
        ],
        "server": ("localhost", 8000),
        "client": ("127.0.0.1", 1),
    }

    async def receive():
        if not status.get("body_sent"):
            status["body_sent"] = True
            return {"type": "http.request", "body": b"{}", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            status["status"] = message["status"]
        elif message["type"] == "http.response.body":
            status["body"] = status.get("body", b"") + message.get("body", b"")

    await app(scope, receive, send)
    return status.get("status") == 401


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with all dependencies wired up."""
    settings = settings or get_settings()
    engine = build_engine(settings.database_url, settings.data_dir)
    session_factory = build_session_factory(engine)

    # The MCP server is mounted as a Starlette sub-app below. Starlette does
    # not run mounted-app lifespans, so its lifespan (which starts the
    # streamable-HTTP session manager) is nested into the FastAPI lifespan.
    mcp_starlette = None
    if settings.mcp_enabled:
        from mcp.server.transport_security import TransportSecuritySettings

        from app.mcp_server import build_mcp_server

        mcp_starlette = build_mcp_server(session_factory, settings).streamable_http_app(
            streamable_http_path="/",
            json_response=True,
            # InfraMP is a self-hosted app reachable through arbitrary hosts
            # (localhost, LAN IPs, domains); the SDK's default localhost-only
            # DNS-rebinding guard would reject every non-loopback Host header.
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine
        app.state.session_factory = session_factory
        with session_factory() as session:
            seed_admin(session, settings)
        if mcp_starlette is not None:
            async with mcp_starlette.router.lifespan_context(mcp_starlette):
                yield
        else:
            yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan, debug=settings.debug)
    app.state.settings = settings
    app.state.login_limiter = LoginRateLimiter(
        max_attempts=settings.login_max_attempts,
        window_seconds=settings.login_window_seconds,
        cooldown_seconds=settings.login_cooldown_seconds,
    )

    app.add_middleware(SecurityHeadersMiddleware, hsts_enabled=settings.hsts_enabled)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)

    # Health endpoints. Defined before the mounts so that ``/mcp/readyz`` is
    # served by this app instead of being swallowed by the ``/mcp`` sub-app.
    @app.get("/healthz", tags=["health"])
    def healthz() -> JSONResponse:
        """Liveness: the process is up and serving. No dependency checks."""
        return JSONResponse(content={"status": "ok"})

    @app.get("/readyz", tags=["health"])
    def readyz() -> JSONResponse:
        """Readiness: the database is reachable and answering queries."""
        try:
            with session_factory() as session:
                session.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - only on broken databases
            logger.exception("Readiness check failed", exc_info=exc)
            return JSONResponse(status_code=503, content={"status": "unhealthy"})
        return JSONResponse(content={"status": "ok"})

    @app.get("/mcp/readyz", tags=["health"])
    async def mcp_readyz() -> JSONResponse:
        """Readiness of the embedded MCP endpoint.

        When MCP is intentionally disabled the app is in its intended state
        and the check reports healthy with ``mcp: disabled``; otherwise it
        probes the transport in-process.
        """
        if mcp_starlette is None:
            return JSONResponse(content={"status": "ok", "mcp": "disabled"})
        try:
            ready = await _mcp_responds(mcp_starlette)
        except Exception as exc:  # pragma: no cover - transport failures
            logger.exception("MCP readiness check failed", exc_info=exc)
            ready = False
        if not ready:
            return JSONResponse(
                status_code=503, content={"status": "unhealthy", "mcp": "not responding"}
            )
        return JSONResponse(content={"status": "ok", "mcp": "enabled"})

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    if mcp_starlette is not None:

        class _MCPPassthrough:
            """Serve ``/mcp`` (no trailing slash) without a redirect hop.

            Starlette's Mount regex requires the trailing slash, so a request
            to exactly ``/mcp`` misses the mount and falls through to a
            redirect-slashes 307. This route rewrites the path (and root_path,
            taking over the mount's prefix stripping) and invokes the MCP app
            directly. The mount below still serves ``/mcp/`` and any subpaths.
            """

            def __init__(self, app):
                self.app = app

            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    scope["path"] = "/mcp/"
                    scope["root_path"] = scope.get("root_path", "") + "/mcp"
                await self.app(scope, receive, send)

        app.router.routes.insert(
            0,
            Route(
                "/mcp",
                endpoint=_MCPPassthrough(mcp_starlette),
                methods=["GET", "POST", "DELETE"],
            ),
        )
        app.mount("/mcp", mcp_starlette, name="mcp")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 401:
            login_url = "/login"
            if request.url.path not in ("", "/", "/login"):
                login_url = f"/login?next={quote(request.url.path)}"
            # HTMX would otherwise follow the 303 and swap the full login page
            # into a fragment target; HX-Redirect triggers a proper navigation.
            if is_htmx(request):
                return Response(status_code=401, headers={"HX-Redirect": login_url})
            return RedirectResponse(login_url, status_code=303)
        if exc.status_code == 404:
            return render(
                request,
                "error.html",
                {"code": 404, "message": "The page you're looking for doesn't exist."},
                status_code=404,
            )
        if exc.status_code == 403:
            return render(
                request,
                "error.html",
                {"code": 403, "message": "You don't have permission to access this page."},
                status_code=403,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Unhandled exceptions must not leak FastAPI's raw JSON to browser
        # users; render the styled error page (fragment for HTMX requests).
        logger.exception("Unhandled error while serving %s", request.url.path, exc_info=exc)
        return render(
            request,
            "error.html",
            {"code": 500, "message": "Something went wrong. Please try again."},
            status_code=500,
        )

    app.include_router(auth.router)
    app.include_router(api_tokens.router)
    app.include_router(backup.router)
    app.include_router(dashboard.router)
    app.include_router(entities.router)
    app.include_router(records.router)
    app.include_router(users.router)
    app.include_router(views.router)

    return app


app = create_app()
