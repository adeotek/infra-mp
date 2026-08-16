"""Tests for the record engine (dynamic validation and CRUD)."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import (
    create_record,
    list_records,
    soft_delete_record,
    update_record,
    validate_record_data,
)
from app.services.schema_service import (
    add_attribute,
    create_entity,
    get_entity_with_attributes,
)


@pytest.fixture
def server_entity(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Hostname", data_type=DataType.TEXT, is_required=True),
    )
    add_attribute(db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER))
    add_attribute(db_session, entity, AttributeCreate(name="Online", data_type=DataType.BOOLEAN))
    add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Status", data_type=DataType.ENUM, options=["active", "retired"]),
    )
    return get_entity_with_attributes(db_session, entity.id)


def test_required_field_missing_is_an_error(db_session, server_entity):
    _, errors = validate_record_data(db_session, server_entity.attributes, {"cores": "4"})
    assert any("Hostname" in e for e in errors)


def test_values_are_coerced(db_session, server_entity):
    data, errors = validate_record_data(
        db_session,
        server_entity.attributes,
        {"hostname": "web01", "cores": "8", "online": "on", "status": "active"},
    )
    assert not errors
    assert data["cores"] == 8
    assert data["online"] is True


def test_enum_membership_is_enforced(db_session, server_entity):
    _, errors = validate_record_data(
        db_session, server_entity.attributes, {"hostname": "web01", "status": "bogus"}
    )
    assert any("Status" in e for e in errors)


def test_unchecked_boolean_is_false(db_session, server_entity):
    data, errors = validate_record_data(db_session, server_entity.attributes, {"hostname": "web01"})
    assert not errors
    assert data["online"] is False


def test_create_and_soft_delete(db_session, server_entity):
    record = create_record(
        db_session, server_entity, server_entity.attributes, {"hostname": "web01"}
    )
    assert list_records(db_session, server_entity.id)
    soft_delete_record(db_session, record)
    assert not list_records(db_session, server_entity.id)


def test_update_record(db_session, server_entity):
    record = create_record(
        db_session, server_entity, server_entity.attributes, {"hostname": "web01"}
    )
    update_record(
        db_session, record, server_entity.attributes, {"hostname": "web01", "cores": "16"}
    )
    assert record.data["cores"] == 16


def test_reference_many_coerces_to_int_list(db_session):
    tag = create_entity(db_session, EntityCreate(name="Tag"))
    server = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(
        db_session,
        server,
        AttributeCreate(
            name="Tags",
            data_type=DataType.REFERENCE,
            reference_entity_id=tag.id,
            cardinality="many",
        ),
    )
    server = get_entity_with_attributes(db_session, server.id)
    data, errors = validate_record_data(db_session, server.attributes, {"tags": ["1", "2"]})
    assert not errors
    assert data["tags"] == [1, 2]


def test_create_record_excludes_inactive_attributes(db_session, server_entity):
    for attr in server_entity.attributes:
        if attr.slug == "cores":
            attr.is_active = False
    db_session.commit()
    record = create_record(
        db_session, server_entity, server_entity.attributes, {"hostname": "web01", "cores": "8"}
    )
    assert "cores" not in record.data


def test_update_record_preserves_inactive_attribute_value(db_session, server_entity):
    record = create_record(
        db_session, server_entity, server_entity.attributes, {"hostname": "web01", "cores": "8"}
    )
    for attr in server_entity.attributes:
        if attr.slug == "cores":
            attr.is_active = False
    db_session.commit()
    update_record(db_session, record, server_entity.attributes, {"hostname": "web01-renamed"})
    assert record.data["hostname"] == "web01-renamed"
    assert record.data["cores"] == 8
