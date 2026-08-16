"""User management routes (admin-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import require_capability
from app.auth.permissions import MANAGE_USERS
from app.db import get_session
from app.flash import redirect_with_flash
from app.form import parse_form
from app.models.enums import Role
from app.models.user import User
from app.services.user_service import (
    UserError,
    create_user,
    delete_user,
    get_user,
    list_users,
    update_user,
)
from app.templates import render

router = APIRouter()


def _coerce_role(value: str) -> Role:
    try:
        return Role(value)
    except ValueError:
        return Role.VIEWER


@router.get("/users")
def users_index(
    request: Request,
    user: User = Depends(require_capability(MANAGE_USERS)),
    db: Session = Depends(get_session),
):
    return render(
        request,
        "users/list.html",
        {"users": list_users(db), "current_user_id": user.id},
    )


@router.get("/users/new")
def new_user_page(request: Request, user: User = Depends(require_capability(MANAGE_USERS))):
    return render(request, "users/form.html", {"target_user": None, "roles": list(Role)})


@router.post("/users")
async def create_user_post(
    request: Request,
    user: User = Depends(require_capability(MANAGE_USERS)),
    db: Session = Depends(get_session),
):
    raw = await parse_form(request)
    username = str(raw.get("username", "")).strip()
    password = str(raw.get("password", ""))
    try:
        create_user(
            db,
            username,
            str(raw.get("display_name", "")),
            _coerce_role(str(raw.get("role", "viewer"))),
            password,
        )
    except UserError as exc:
        return render(
            request,
            "users/form.html",
            {
                "target_user": None,
                "roles": list(Role),
                "error": str(exc),
                "form": {
                    "username": username,
                    "display_name": raw.get("display_name", ""),
                    "role": raw.get("role", "viewer"),
                },
            },
            status_code=400,
        )
    return redirect_with_flash("/users", f"User '{username}' created.")


@router.get("/users/{user_id}/edit")
def edit_user_page(
    request: Request,
    user_id: int,
    user: User = Depends(require_capability(MANAGE_USERS)),
    db: Session = Depends(get_session),
):
    target = get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    return render(request, "users/form.html", {"target_user": target, "roles": list(Role)})


@router.post("/users/{user_id}/edit")
async def update_user_post(
    request: Request,
    user_id: int,
    user: User = Depends(require_capability(MANAGE_USERS)),
    db: Session = Depends(get_session),
):
    target = get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    raw = await parse_form(request)
    update_user(
        db,
        target,
        str(raw.get("display_name", "")),
        _coerce_role(str(raw.get("role", "viewer"))),
        "is_active" in raw,
        str(raw.get("password", "")) or None,
    )
    return redirect_with_flash("/users", f"User '{target.username}' updated.")


@router.post("/users/{user_id}/delete")
def delete_user_post(
    request: Request,
    user_id: int,
    user: User = Depends(require_capability(MANAGE_USERS)),
    db: Session = Depends(get_session),
):
    target = get_user(db, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    try:
        delete_user(db, target, user)
    except UserError as exc:
        return redirect_with_flash("/users", str(exc), category="error")
    return redirect_with_flash("/users", f"User '{target.username}' deleted.")
