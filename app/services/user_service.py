"""User management business logic."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.password import hash_password, verify_password
from app.models.enums import Role
from app.models.user import User


class UserError(ValueError):
    """Raised for invalid user operations."""


def list_users(db: Session) -> list[User]:
    return list(db.execute(select(User).order_by(User.username)).scalars())


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def username_exists(db: Session, username: str, exclude_id: int | None = None) -> bool:
    query = select(User.id).where(User.username == username)
    if exclude_id is not None:
        query = query.where(User.id != exclude_id)
    return db.execute(query).first() is not None


def create_user(
    db: Session,
    username: str,
    display_name: str,
    role: Role,
    password: str,
) -> User:
    username = username.strip()
    if not username:
        raise UserError("Username is required.")
    if len(username) < 2:
        raise UserError("Username must be at least 2 characters.")
    if username_exists(db, username):
        raise UserError(f"Username '{username}' is already taken.")
    user = User(
        username=username,
        display_name=display_name.strip(),
        role=role.value,
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    return user


def update_user(
    db: Session,
    user: User,
    display_name: str,
    role: Role,
    is_active: bool,
    password: str | None = None,
    username: str | None = None,
) -> User:
    # The username is only changed when provided (the web form always sends
    # it; older API-style callers may omit it to keep the current value).
    if username is not None:
        username = username.strip()
        if not username:
            raise UserError("Username is required.")
        if len(username) < 2:
            raise UserError("Username must be at least 2 characters.")
        if username_exists(db, username, exclude_id=user.id):
            raise UserError(f"Username '{username}' is already taken.")
        user.username = username
    user.display_name = display_name.strip()
    user.role = role.value
    user.is_active = is_active
    if password:
        user.password_hash = hash_password(password)
    db.commit()
    return user


def delete_user(db: Session, user: User, current_user: User) -> None:
    if user.id == current_user.id:
        raise UserError("You cannot delete your own account.")
    if user.role == Role.ADMIN.value and user.is_active:
        active_admins = db.execute(
            select(func.count(User.id)).where(
                User.role == Role.ADMIN.value, User.is_active.is_(True)
            )
        ).scalar_one()
        if active_admins <= 1:
            raise UserError("Cannot delete the last active admin.")
    db.delete(user)
    db.commit()


def change_password(db: Session, user: User, current_password: str, new_password: str) -> User:
    """Update a user's own password, verifying the current one first."""
    if not verify_password(current_password, user.password_hash):
        raise UserError("Current password is incorrect.")
    if len(new_password) < 8:
        raise UserError("New password must be at least 8 characters.")
    if new_password == current_password:
        raise UserError("New password must be different from the current password.")
    user.password_hash = hash_password(new_password)
    db.commit()
    return user
