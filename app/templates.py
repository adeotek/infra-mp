"""Jinja2 template setup and a render helper."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import get_settings
from app.security.csrf import csrf_token_for

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _datetime_local(value) -> str:
    """Format a value for <input type="datetime-local"> (str or datetime)."""
    if isinstance(value, datetime):
        value = value.isoformat()
    return (value or "")[:16]


templates.env.filters["datetime_local"] = _datetime_local


def _datetime_display(value) -> str:
    """Format a timestamp for display (naive UTC -> "YYYY-MM-DD HH:MM")."""
    if not value:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M")


templates.env.filters["datetime_display"] = _datetime_display


def _icon_class(value, fallback: str = "fa-cube") -> str:
    """Normalise a stored icon value into a FontAwesome solid class."""
    value = (value or "").strip()
    if not value:
        return fallback
    if value.startswith("fa-"):
        return value
    return f"fa-{value}"


templates.env.filters["icon_class"] = _icon_class


def _safe_url(value) -> str | None:
    """Render-time http(s)-only guard for href attributes.

    Server-side validation rejects non-http(s) ``link`` values, but anchors
    must not depend on that single check holding for every write path (imports,
    MCP, legacy rows): a ``javascript:``/``data:`` scheme would slip through
    autoescaping, so non-http(s) values render as a plain-text cell instead.
    """
    if not value:
        return None
    try:
        parsed = urlparse(str(value))
    except ValueError:
        return None
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return str(value)
    return None


templates.env.filters["safe_url"] = _safe_url

# Fixed set of flash categories; never interpolate raw query params into
# class attributes.
_FLASH_TYPES = frozenset({"success", "error"})


def is_htmx(request: Request) -> bool:
    """True when the request was issued by HTMX (sets the ``HX-Request`` header)."""
    return request.headers.get("HX-Request", "").lower() == "true"


def render(
    request: Request,
    template_name: str,
    context: dict | None = None,
    status_code: int = 200,
):
    """Render a template with common context (current user, app name).

    HTMX requests get ``base_template="fragment.html"`` (and ``is_fragment=True``)
    so form templates render as bare fragments for a modal, while ordinary
    requests keep the full page layout as a no-JS fallback.
    """
    fragment = is_htmx(request)
    flash_type = request.query_params.get("flash_type", "success")
    ctx: dict = {
        "current_user": getattr(request.state, "current_user", None),
        "current_path": request.url.path,
        "app_name": get_settings().app_name,
        "app_version": __version__,
        "base_url": get_settings().base_url,
        "flash": request.query_params.get("flash"),
        "flash_type": flash_type if flash_type in _FLASH_TYPES else "success",
        "is_fragment": fragment,
        "base_template": "fragment.html" if fragment else "base.html",
        "csrf_token": csrf_token_for(request),
    }
    if context:
        ctx.update(context)
    # The sidebar lists every custom view and entity; skip the query for htmx fragments.
    if not fragment and ctx["current_user"] is not None:
        factory = getattr(request.app.state, "session_factory", None)
        if factory is not None:
            from app.services.schema_service import list_entities
            from app.services.view_service import list_views

            with factory() as session:
                ctx["sidebar_views"] = list_views(session)
                ctx["sidebar_entities"] = list_entities(session)
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)
