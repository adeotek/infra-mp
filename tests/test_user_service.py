"""Service-level tests for user management and input validation."""

import pytest

from app.auth.password import verify_password
from app.models.enums import DataType, Role
from app.models.record import Record
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import create_record
from app.services.schema_service import add_attribute, create_entity, get_entity_with_attributes
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
    # A second active admin must exist before the first can be demoted.
    create_user(db_session, "root", "Root", Role.ADMIN, "password-123")
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
    # Deactivation of the only admin is guarded; a second admin must exist.
    create_user(db_session, "root", "Root", Role.ADMIN, "password-123")
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
# Input validation (enforced in the service; the old pydantic schemas are gone)
# --------------------------------------------------------------------------- #


def test_create_user_username_too_short(db_session):
    with pytest.raises(UserError, match="at least 2"):
        create_user(db_session, "a", "A", Role.VIEWER, "password-123")


def test_create_user_password_too_short(db_session):
    with pytest.raises(UserError, match="at least 8"):
        create_user(db_session, "valid", "Valid", Role.VIEWER, "short")


def test_create_user_defaults(db_session):
    user = create_user(db_session, "valid", "", Role.VIEWER, "password-123")
    assert user.role == Role.VIEWER.value
    assert user.display_name == ""


def test_delete_user_with_authored_records_nulls_attribution(db_session):
    admin = create_user(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    author = create_user(db_session, "author", "Author", Role.MAINTAINER, "password-123")
    entity = create_entity(db_session, EntityCreate(name="Servers"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    entity = get_entity_with_attributes(db_session, entity.id)
    record = create_record(
        db_session, entity, entity.attributes, {"name": "srv1"}, user_id=author.id
    )

    delete_user(db_session, author, admin)

    assert get_user(db_session, author.id) is None
    db_session.expire_all()
    reloaded = db_session.get(Record, record.id)
    assert reloaded is not None
    assert reloaded.created_by is None
    assert reloaded.updated_by is None
