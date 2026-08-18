"""Jinja2 template setup and a render helper."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

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
        "flash": request.query_params.get("flash"),
        "flash_type": request.query_params.get("flash_type", "success"),
        "is_fragment": fragment,
        "base_template": "fragment.html" if fragment else "base.html",
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)
