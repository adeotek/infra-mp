"""Flash message helpers (query-param based, stateless)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import RedirectResponse


def redirect_with_flash(url: str, message: str, category: str = "success") -> RedirectResponse:
    """Redirect to ``url`` carrying a one-shot flash message."""
    sep = "&" if "?" in url else "?"
    return RedirectResponse(
        f"{url}{sep}flash={quote(message)}&flash_type={category}",
        status_code=303,
    )
