"""Server-side session management.

Only the SHA-256 hash of a session token is persisted, so a database leak does
not expose valid session tokens.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.mixins import utcnow
from app.models.session import AuthSession
from app.models.user import User


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user_id: int, ttl_days: int) -> str:
    """Create a session for ``user_id`` and return the raw token."""
    delete_expired_sessions(db)
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=_hash_token(token),
            user_id=user_id,
            expires_at=utcnow() + timedelta(days=ttl_days),
        )
    )
    db.commit()
    return token


def resolve_user(db: Session, token: str) -> User | None:
    """Return the user for a raw session token, or None if invalid/expired."""
    session = db.execute(
        select(AuthSession).where(AuthSession.token_hash == _hash_token(token))
    ).scalar_one_or_none()
    if session is None or session.expires_at < utcnow():
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return user


def delete_session(db: Session, token: str) -> None:
    """Invalidate a session by raw token."""
    db.execute(delete(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
    db.commit()


def delete_expired_sessions(db: Session) -> None:
    """Delete all expired sessions."""
    db.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))
    db.commit()
