"""API token management (MCP / agent access credentials).

Two pages share these routes:

- ``/settings/api-tokens`` (sidebar, admin-only): all users' tokens with a
  user filter — admins manage the whole fleet.
- ``/settings/my-tokens`` (header user menu): the current user's own tokens.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_capability
from app.auth.permissions import MANAGE_USERS, has_capability
from app.db import get_session
from app.flash import redirect_with_flash
from app.form import parse_form
from app.models.api_token import ApiToken
from app.models.user import User
from app.services import api_token_service, user_service
from app.templates import render

router = APIRouter()

VALID_RETURN_TO = ("/settings/api-tokens", "/settings/my-tokens")


def _admin_context(db: Session) -> dict:
    """Template context for the admin page: every token + users for the filter."""
    return {
        "tokens": [(t, u) for t, u in api_token_service.list_all_tokens(db)],
        "users": user_service.list_users(db),
        "show_username": True,
        "return_to": "/settings/api-tokens",
    }


def _own_context(db: Session, user: User) -> dict:
    """Template context for the personal page: only the current user's tokens."""
    return {
        "tokens": [(t, None) for t in api_token_service.list_tokens_for_user(db, user.id)],
        "show_username": False,
        "return_to": "/settings/my-tokens",
    }


# ------------------------------------------------------------ admin page (all)


@router.get("/settings/api-tokens")
def api_tokens_index(
    request: Request,
    user: User = Depends(require_capability(MANAGE_USERS)),
    db: Session = Depends(get_session),
):
    return render(request, "api_tokens.html", _admin_context(db))


@router.post("/settings/api-tokens")
async def api_token_create(
    request: Request,
    user: User = Depends(require_capability(MANAGE_USERS)),
    db: Session = Depends(get_session),
):
    raw = await parse_form(request)
    name = str(raw.get("name", "")).strip()
    if not name:
        return render(
            request,
            "api_tokens.html",
            {**_admin_context(db), "form_error": "Token name is required."},
            status_code=400,
        )
    plaintext, token = api_token_service.generate_token(db, user, name)
    # The plaintext is rendered exactly once, on this response; it is never
    # stored and never survives a redirect (which would leak it into cookies).
    return render(
        request,
        "api_tokens.html",
        {**_admin_context(db), "new_token": plaintext, "new_token_name": token.name},
    )


# --------------------------------------------------------- personal page (own)


@router.get("/settings/my-tokens")
def my_tokens_index(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    return render(request, "my_tokens.html", _own_context(db, user))


@router.post("/settings/my-tokens")
async def my_token_create(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    raw = await parse_form(request)
    name = str(raw.get("name", "")).strip()
    if not name:
        return render(
            request,
            "my_tokens.html",
            {**_own_context(db, user), "form_error": "Token name is required."},
            status_code=400,
        )
    plaintext, token = api_token_service.generate_token(db, user, name)
    return render(
        request,
        "my_tokens.html",
        {**_own_context(db, user), "new_token": plaintext, "new_token_name": token.name},
    )


# --------------------------------------------------------------------- revoke


@router.post("/settings/api-tokens/{token_id}/revoke")
async def api_token_revoke(
    token_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    token = db.get(ApiToken, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.user_id != user.id and not has_capability(user, MANAGE_USERS):
        raise HTTPException(status_code=403, detail="Forbidden")
    api_token_service.revoke_token(db, token)
    raw = await parse_form(request)
    return_to = str(raw.get("return_to", ""))
    if return_to not in VALID_RETURN_TO:
        if has_capability(user, MANAGE_USERS):
            return_to = "/settings/api-tokens"
        else:
            return_to = "/settings/my-tokens"
    return redirect_with_flash(
        return_to,
        f"Token '{token.name}' revoked.",
        request=request,
    )
