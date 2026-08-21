"""API token generation and verification."""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.api_token import ApiToken
from app.models.mixins import utcnow
from app.models.user import User

PREFIX = "imp_"


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token(db: Session, user: User, name: str) -> tuple[str, ApiToken]:
    """Create a new token for ``user``.

    Returns ``(plaintext, token)``; the plaintext is shown to the caller once
    and never stored (only its hash is persisted).
    """
    plaintext = PREFIX + secrets.token_hex(24)
    token = ApiToken(
        user_id=user.id,
        name=name.strip(),
        token_hash=_hash(plaintext),
        token_prefix=plaintext[:12],
    )
    db.add(token)
    db.commit()
    return plaintext, token


def verify_token(db: Session, raw_token: str) -> User | None:
    """Return the token's user if it is valid, or ``None``.

    Valid means: an active token belonging to an active user. Updates
    ``last_used_at`` on success.
    """
    if not raw_token or not raw_token.startswith(PREFIX):
        return None
    token = db.execute(
        select(ApiToken).where(ApiToken.token_hash == _hash(raw_token))
    ).scalar_one_or_none()
    if token is None or not token.is_active:
        return None
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        return None
    token.last_used_at = utcnow()
    db.commit()
    return user


def list_tokens_for_user(db: Session, user_id: int) -> list[ApiToken]:
    return list(
        db.execute(
            select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.created_at.desc())
        ).scalars()
    )


def list_all_tokens(db: Session) -> list[tuple[ApiToken, User]]:
    rows = db.execute(
        select(ApiToken, User)
        .join(User, User.id == ApiToken.user_id)
        .order_by(ApiToken.created_at.desc())
    ).all()
    return [(token, user) for token, user in rows]


def revoke_token(db: Session, token: ApiToken) -> None:
    token.is_active = False
    db.commit()
