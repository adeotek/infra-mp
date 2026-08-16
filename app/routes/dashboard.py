"""Dashboard and index routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.templates import render

router = APIRouter()


@router.get("/")
def index() -> RedirectResponse:
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(get_current_user)):
    return render(request, "dashboard.html")
