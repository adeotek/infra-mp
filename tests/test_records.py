"""Tests for the record engine (dynamic validation and CRUD)."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import (
    RecordError,
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


# --------------------------------------------------------------------------- #
# Unique attribute values
# --------------------------------------------------------------------------- #


@pytest.fixture
def unique_entity(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Hostname", data_type=DataType.TEXT, is_unique=True),
    )
    add_attribute(db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER))
    loaded = get_entity_with_attributes(db_session, entity.id)
    assert loaded is not None
    return loaded


def test_unique_duplicate_value_rejected_on_create(db_session, unique_entity):
    create_record(db_session, unique_entity, unique_entity.attributes, {"hostname": "web1"})
    with pytest.raises(RecordError, match="must be unique"):
        create_record(db_session, unique_entity, unique_entity.attributes, {"hostname": "web1"})


def test_unique_distinct_values_accepted(db_session, unique_entity):
    create_record(db_session, unique_entity, unique_entity.attributes, {"hostname": "web1"})
    create_record(db_session, unique_entity, unique_entity.attributes, {"hostname": "web2"})
    assert len(list_records(db_session, unique_entity.id)) == 2


def test_unique_empty_values_are_exempt(db_session, unique_entity):
    create_record(db_session, unique_entity, unique_entity.attributes, {"cores": "4"})
    create_record(db_session, unique_entity, unique_entity.attributes, {"cores": "8"})
    assert len(list_records(db_session, unique_entity.id)) == 2


def test_unique_update_to_duplicate_rejected(db_session, unique_entity):
    create_record(db_session, unique_entity, unique_entity.attributes, {"hostname": "web1"})
    other = create_record(db_session, unique_entity, unique_entity.attributes, {"hostname": "web2"})
    with pytest.raises(RecordError, match="must be unique"):
        update_record(db_session, other, unique_entity.attributes, {"hostname": "web1"})


def test_unique_update_keeping_own_value_accepted(db_session, unique_entity):
    record = create_record(
        db_session, unique_entity, unique_entity.attributes, {"hostname": "web1"}
    )
    update_record(db_session, record, unique_entity.attributes, {"hostname": "web1", "cores": "8"})
    assert record.data["cores"] == 8


def test_unique_soft_deleted_record_does_not_block(db_session, unique_entity):
    old = create_record(db_session, unique_entity, unique_entity.attributes, {"hostname": "web1"})
    soft_delete_record(db_session, old)
    create_record(db_session, unique_entity, unique_entity.attributes, {"hostname": "web1"})
    assert len(list_records(db_session, unique_entity.id)) == 1


# --------------------------------------------------------------------------- #
# Entity key (single or composite): record identity + uniqueness
# --------------------------------------------------------------------------- #


@pytest.fixture
def keyed_entity(db_session):
    entity = create_entity(db_session, EntityCreate(name="Device"))
    add_attribute(
        db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT, is_key=True)
    )
    add_attribute(db_session, entity, AttributeCreate(name="Model", data_type=DataType.TEXT))
    add_attribute(
        db_session, entity, AttributeCreate(name="Vendor", data_type=DataType.TEXT, is_key=True)
    )
    loaded = get_entity_with_attributes(db_session, entity.id)
    assert loaded is not None
    return loaded


def test_key_duplicate_values_rejected_on_create(db_session, keyed_entity):
    create_record(
        db_session, keyed_entity, keyed_entity.attributes, {"name": "nas", "vendor": "TerraMaster"}
    )
    with pytest.raises(RecordError, match="key values must be unique"):
        create_record(
            db_session,
            keyed_entity,
            keyed_entity.attributes,
            {"name": "nas", "vendor": "TerraMaster"},
        )


def test_key_partial_difference_accepted(db_session, keyed_entity):
    # Composite key: differing on any key attribute is fine.
    create_record(
        db_session, keyed_entity, keyed_entity.attributes, {"name": "nas", "vendor": "TerraMaster"}
    )
    create_record(
        db_session, keyed_entity, keyed_entity.attributes, {"name": "nas", "vendor": "Synology"}
    )
    assert len(list_records(db_session, keyed_entity.id)) == 2


def test_key_missing_values_are_exempt(db_session, keyed_entity):
    create_record(db_session, keyed_entity, keyed_entity.attributes, {"name": "nas"})
    create_record(db_session, keyed_entity, keyed_entity.attributes, {"name": "nas"})
    assert len(list_records(db_session, keyed_entity.id)) == 2


def test_key_update_to_duplicate_rejected(db_session, keyed_entity):
    create_record(db_session, keyed_entity, keyed_entity.attributes, {"name": "nas", "vendor": "A"})
    other = create_record(
        db_session, keyed_entity, keyed_entity.attributes, {"name": "nas2", "vendor": "B"}
    )
    with pytest.raises(RecordError, match="key values must be unique"):
        update_record(db_session, other, keyed_entity.attributes, {"name": "nas", "vendor": "A"})


def test_key_update_keeping_own_values_accepted(db_session, keyed_entity):
    record = create_record(
        db_session, keyed_entity, keyed_entity.attributes, {"name": "nas", "vendor": "A"}
    )
    update_record(
        db_session, record, keyed_entity.attributes, {"name": "nas", "vendor": "A", "model": "X"}
    )
    assert record.data["model"] == "X"
