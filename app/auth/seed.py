"""Seed the initial admin user on first startup."""

from __future__ import annotations

import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.config import Settings
from app.models.enums import Role
from app.models.user import User


def seed_admin(db: Session, settings: Settings) -> None:
    """Create the admin account if no users exist yet.

    Returns without doing anything if the database has already been initialised
    (i.e. at least one user exists).
    """
    has_users = db.execute(select(func.count(User.id))).scalar_one() > 0
    if has_users:
        return

    password = settings.admin_password or secrets.token_urlsafe(12)
    db.add(
        User(
            username=settings.admin_username,
            display_name=settings.admin_display_name,
            password_hash=hash_password(password),
            role=Role.ADMIN.value,
            is_active=True,
        )
    )
    db.commit()

    if not settings.admin_password:
        print(
            f"[homelab-manager] Seeded admin user '{settings.admin_username}' "
            f"with password: {password}"
        )
        print(
            "[homelab-manager] Log in and change it, or set HOMELAB_ADMIN_PASSWORD "
            "and restart."
        )
