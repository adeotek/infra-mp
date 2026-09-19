"""Seed the initial admin user on first startup."""

from __future__ import annotations

import secrets
from pathlib import Path

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
        # Log that a generated password exists — but NEVER its value: stdout
        # lands in container logs and log collectors, where a credential
        # would be exposed to anyone with log access. The value goes to a
        # 0600 file inside the data directory instead.
        try:
            data_dir = Path(settings.data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            cred_file = data_dir / "initial-admin-password.txt"
            cred_file.write_text(
                f"admin = {settings.admin_username} = {password}\n"
                "(delete this file after signing in)\n",
                encoding="utf-8",
            )
            cred_file.chmod(0o600)
            print(
                f"[infra-mp] Seeded admin user '{settings.admin_username}' with a generated "
                f"password, written to {cred_file} (permissions 0600)."
            )
            print(
                "[infra-mp] Log in, change it, then delete the file — or set "
                "INFRAMP_ADMIN_PASSWORD and restart."
            )
        except OSError:
            print(
                "[infra-mp] Seeded admin user, but the generated password could not be "
                "written to disk. Set INFRAMP_ADMIN_PASSWORD and restart, or reset the "
                "admin user manually."
            )
