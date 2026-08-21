"""API token management (MCP / agent access credentials)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.permissions import MANAGE_USERS, has_capability
from app.db import get_session
from app.flash import redirect_with_flash
from app.form import parse_form
from app.models.api_token import ApiToken
from app.models.user import User
from app.services import api_token_service
from app.templates import render

router = APIRouter()


def _tokens_context(db: Session, user: User) -> dict:
    """Build the template context: own tokens, or all tokens for admins."""
    if has_capability(user, MANAGE_USERS):
        return {
            "tokens": [(t, u) for t, u in api_token_service.list_all_tokens(db)],
            "show_username": True,
        }
    return {
        "tokens": [(t, None) for t in api_token_service.list_tokens_for_user(db, user.id)],
        "show_username": False,
    }


@router.get("/settings/api-tokens")
def api_tokens_index(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    return render(request, "api_tokens.html", _tokens_context(db, user))


@router.post("/settings/api-tokens")
async def api_token_create(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    raw = await parse_form(request)
    name = str(raw.get("name", "")).strip()
    if not name:
        return render(
            request,
            "api_tokens.html",
            {**_tokens_context(db, user), "form_error": "Token name is required."},
            status_code=400,
        )
    plaintext, token = api_token_service.generate_token(db, user, name)
    # The plaintext is rendered exactly once, on this response; it is never
    # stored and never survives a redirect (which would leak it into cookies).
    return render(
        request,
        "api_tokens.html",
        {**_tokens_context(db, user), "new_token": plaintext, "new_token_name": token.name},
    )


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
    return redirect_with_flash(
        "/settings/api-tokens",
        f"Token '{token.name}' revoked.",
        request=request,
    )
