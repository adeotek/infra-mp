"""Jinja2 template setup and a render helper."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import get_settings

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# Format an ISO datetime ("YYYY-MM-DDTHH:MM:SS") for <input type="datetime-local">.
templates.env.filters["datetime_local"] = lambda value: (value or "")[:16]


def render(
    request: Request,
    template_name: str,
    context: dict | None = None,
    status_code: int = 200,
):
    """Render a template with common context (current user, app name)."""
    ctx: dict = {
        "current_user": getattr(request.state, "current_user", None),
        "app_name": get_settings().app_name,
        "flash": request.query_params.get("flash"),
        "flash_type": request.query_params.get("flash_type", "success"),
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)
