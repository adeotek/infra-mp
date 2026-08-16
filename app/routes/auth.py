"""Authentication routes: login page, login, logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.password import verify_password
from app.auth.sessions import create_session, delete_session
from app.config import get_settings
from app.db import get_session
from app.flash import redirect_with_flash
from app.models.user import User
from app.services.user_service import UserError, change_password
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


@router.get("/settings/password")
def change_password_page(request: Request, user: User = Depends(get_current_user)):
    return render(request, "change_password.html", {})


@router.post("/settings/password")
def change_password_post(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    if new_password != confirm_password:
        return render(
            request,
            "change_password.html",
            {"error": "New passwords do not match."},
            status_code=400,
        )
    try:
        change_password(db, user, current_password, new_password)
    except UserError as exc:
        return render(request, "change_password.html", {"error": str(exc)}, status_code=400)
    return redirect_with_flash("/dashboard", "Password changed.")
