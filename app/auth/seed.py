"""Seed the initial admin user on first startup."""

from __future__ import annotations

import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.config import Settings
from app.models.enums import Role
from app.models.user import User
from app.services.user_service import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


def _valid_seed_password(password: str) -> bool:
    """The seeding path enforces the same floor as every other password."""
    return MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH


def seed_admin(db: Session, settings: Settings) -> None:
    """Create the admin account if no users exist yet.

    Returns without doing anything if the database has already been initialised
    (i.e. at least one user exists). The insert is guarded against the race of
    two processes seeding concurrently: the loser's unique-username violation
    is caught and ignored.
    """
    has_users = db.execute(select(func.count(User.id))).scalar_one() > 0
    if has_users:
        return

    password = settings.admin_password or secrets.token_urlsafe(12)
    if not _valid_seed_password(password):
        raise RuntimeError(
            "INFRAMP_ADMIN_PASSWORD must be between "
            f"{MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters."
        )
    db.add(
        User(
            username=settings.admin_username,
            display_name=settings.admin_display_name,
            password_hash=hash_password(password),
            role=Role.ADMIN.value,
            is_active=True,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Another process seeded first; nothing to do.
        db.rollback()
        return

    if not settings.admin_password:
        # NOTE: the generated password is deliberately logged so the operator
        # can log in on first boot — it is visible in container logs and any
        # log collector. Change it immediately or pin INFRAMP_ADMIN_PASSWORD.
        print(f"[infra-mp] Seeded admin user '{settings.admin_username}' with password: {password}")
        print("[infra-mp] Log in and change it, or set INFRAMP_ADMIN_PASSWORD and restart.")
