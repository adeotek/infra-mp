"""Authentication routes: login page, login, logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import verify_password
from app.auth.sessions import create_session, delete_session
from app.config import get_settings
from app.db import get_session
from app.models.user import User
from app.templates import render

router = APIRouter()


def _safe_next(value: str | None) -> str:
    """Allow only relative redirect targets (prevents open redirects)."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", {"next": request.query_params.get("next", "")})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_session),
):
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return render(
            request,
            "login.html",
            {"error": "Invalid username or password.", "next": next},
            status_code=401,
        )

    settings = get_settings()
    token = create_session(db, user.id, settings.session_ttl_days)
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.session_ttl_days * 86400,
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_session)):
    token = request.cookies.get(get_settings().session_cookie_name)
    if token:
        delete_session(db, token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(get_settings().session_cookie_name)
    return response
