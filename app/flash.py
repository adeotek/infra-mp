"""Flash message helpers (query-param based, stateless)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from app.templates import is_htmx


def redirect_with_flash(
    url: str,
    message: str,
    category: str = "success",
    request: Request | None = None,
) -> Response:
    """Redirect to ``url`` carrying a one-shot flash message.

    For HTMX requests the flash target is returned as an ``HX-Redirect`` header
    so the client performs a full navigation (closing any open modal) and the
    flash is shown on the resulting page. Otherwise a standard 303 redirect is
    returned.
    """
    sep = "&" if "?" in url else "?"
    target = f"{url}{sep}flash={quote(message)}&flash_type={category}"
    if request is not None and is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": target})
    return RedirectResponse(target, status_code=303)
