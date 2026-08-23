"""API token generation and verification."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.api_token import ApiToken
from app.models.mixins import utcnow
from app.models.user import User

PREFIX = "imp_"

# last_used_at is only rewritten when the previous write is older than this,
# so read-heavy MCP traffic doesn't commit a write transaction per request.
LAST_USED_THROTTLE_SECONDS = 60


def _hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token(
    db: Session,
    user: User,
    name: str,
    expires_at: datetime | None = None,
) -> tuple[str, ApiToken]:
    """Create a new token for ``user``.

    Returns ``(plaintext, token)``; the plaintext is shown to the caller once
    and never stored (only its hash is persisted). ``expires_at`` (naive UTC)
    optionally bounds the token's lifetime.
    """
    plaintext = PREFIX + secrets.token_hex(24)
    token = ApiToken(
        user_id=user.id,
        name=name.strip(),
        token_hash=_hash(plaintext),
        token_prefix=plaintext[:12],
        expires_at=expires_at,
    )
    db.add(token)
    db.commit()
    return plaintext, token


def verify_token(db: Session, raw_token: str) -> User | None:
    """Return the token's user if it is valid, or ``None``.

    Valid means: an active, unexpired token belonging to an active user.
    Updates ``last_used_at`` on success, throttled so it is written at most
    once per minute (no commit at all when nothing changed).
    """
    if not raw_token or not raw_token.startswith(PREFIX):
        return None
    token = db.execute(
        select(ApiToken).where(ApiToken.token_hash == _hash(raw_token))
    ).scalar_one_or_none()
    if token is None or not token.is_active:
        return None
    if token.expires_at is not None and token.expires_at < utcnow():
        return None
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        return None
    now = utcnow()
    if token.last_used_at is None or token.last_used_at < now - timedelta(
        seconds=LAST_USED_THROTTLE_SECONDS
    ):
        token.last_used_at = now
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


def delete_token(db: Session, token: ApiToken) -> None:
    """Permanently remove a token (revoked tokens only — enforced by callers)."""
    db.delete(token)
    db.commit()
