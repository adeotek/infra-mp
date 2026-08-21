"""Service-level tests for user management, plus the user input schemas."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.auth.password import verify_password
from app.models.enums import Role
from app.schemas.user import UserCreate, UserUpdate
from app.services.user_service import (
    UserError,
    change_password,
    create_user,
    delete_user,
    get_user,
    list_users,
    update_user,
    username_exists,
)

# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


def test_create_user_duplicate(db_session):
    create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    with pytest.raises(UserError, match="already taken"):
        create_user(db_session, "admin", "Admin 2", Role.VIEWER, "password-123")


def test_username_exists_and_list_get(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    assert username_exists(db_session, "admin")
    assert not username_exists(db_session, "nobody")
    assert not username_exists(db_session, "admin", exclude_id=admin.id)
    assert list_users(db_session) == [admin]
    assert get_user(db_session, admin.id) is admin


def test_update_user_changes_fields_and_password(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    update_user(db_session, admin, "New Name", Role.VIEWER, True, "new-password-456")
    assert admin.display_name == "New Name"
    assert admin.role == Role.VIEWER.value
    assert verify_password("new-password-456", admin.password_hash)


def test_update_user_changes_username(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    update_user(db_session, admin, "Admin", Role.ADMIN, True, username="root")
    assert admin.username == "root"
    # The previous username is freed and can be reused by a new account.
    create_user(db_session, "admin", "Admin 2", Role.VIEWER, "password-123")


def test_update_user_duplicate_username_rejected(db_session):
    create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    bob = create_user(db_session, "bob", "Bob", Role.VIEWER, "password-123")
    with pytest.raises(UserError, match="already taken"):
        update_user(db_session, bob, "Bob", Role.VIEWER, True, username="admin")


def test_update_user_blank_username_rejected(db_session):
    bob = create_user(db_session, "bob", "Bob", Role.VIEWER, "password-123")
    with pytest.raises(UserError, match="required"):
        update_user(db_session, bob, "Bob", Role.VIEWER, True, username="  ")
    with pytest.raises(UserError, match="at least 2"):
        update_user(db_session, bob, "Bob", Role.VIEWER, True, username="b")


def test_update_user_without_username_keeps_it(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    update_user(db_session, admin, "Renamed", Role.ADMIN, True)
    assert admin.username == "admin"


def test_delete_self_is_rejected(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    with pytest.raises(UserError, match="own account"):
        delete_user(db_session, admin, admin)


def test_delete_last_active_admin_is_rejected(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    other = create_user(db_session, "other", "Other", Role.VIEWER, "password-123")
    with pytest.raises(UserError, match="last active admin"):
        delete_user(db_session, admin, other)


def test_delete_inactive_admin_allowed(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    update_user(db_session, admin, "Admin", Role.ADMIN, False)  # deactivate
    other = create_user(db_session, "other", "Other", Role.VIEWER, "password-123")
    delete_user(db_session, admin, other)
    assert get_user(db_session, admin.id) is None


def test_change_password_wrong_current(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    with pytest.raises(UserError, match="incorrect"):
        change_password(db_session, admin, "wrong", "new-password-123")


def test_change_password_too_short(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    with pytest.raises(UserError, match="at least 8"):
        change_password(db_session, admin, "password-123", "short")


def test_change_password_same_as_current(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    with pytest.raises(UserError, match="different"):
        change_password(db_session, admin, "password-123", "password-123")


def test_change_password_success(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    change_password(db_session, admin, "password-123", "new-password-456")
    assert verify_password("new-password-456", admin.password_hash)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


def test_user_create_validation():
    with pytest.raises(PydanticValidationError):
        UserCreate(username="a", password="password-123")  # username too short
    with pytest.raises(PydanticValidationError):
        UserCreate(username="valid", password="short")  # password too short
    user = UserCreate(username="valid", password="password-123")
    assert user.role == Role.VIEWER
    assert user.display_name == ""


def test_user_update_defaults():
    update = UserUpdate()
    assert update.display_name == ""
    assert update.role == Role.VIEWER
    assert update.is_active is True
    assert update.password is None
