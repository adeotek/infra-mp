"""Application factory and entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Route

from app.auth.seed import seed_admin
from app.config import Settings, get_settings
from app.db import build_engine, build_session_factory
from app.routes import api_tokens, auth, backup, dashboard, entities, records, users, views
from app.templates import render

STATIC_DIR = Path(__file__).parent / "static"


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

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

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

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

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
