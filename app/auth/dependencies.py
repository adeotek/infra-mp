"""FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.permissions import has_capability
from app.auth.sessions import resolve_user
from app.config import get_settings
from app.db import get_session
from app.models.user import User


def get_current_user(
    request: Request,
    db: Session = Depends(get_session),
) -> User:
    """Return the authenticated user.

    Raises ``HTTPException(401)`` when unauthenticated; the application's
    exception handler converts that into a redirect to the login page.
    """
    token = request.cookies.get(get_settings().session_cookie_name)
    if token:
        user = resolve_user(db, token)
        if user is not None:
            request.state.current_user = user
            return user
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_capability(capability: str):
    """Dependency factory enforcing a capability for the current user."""

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if not has_capability(user, capability):
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return _dependency
