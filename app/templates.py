"""Jinja2 template setup and a render helper."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import get_settings

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Format an ISO datetime ("YYYY-MM-DDTHH:MM:SS") for <input type="datetime-local">.
templates.env.filters["datetime_local"] = lambda value: (value or "")[:16]


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
    ctx: dict = {
        "current_user": getattr(request.state, "current_user", None),
        "current_path": request.url.path,
        "app_name": get_settings().app_name,
        "app_version": __version__,
        "flash": request.query_params.get("flash"),
        "flash_type": request.query_params.get("flash_type", "success"),
        "is_fragment": fragment,
        "base_template": "fragment.html" if fragment else "base.html",
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
