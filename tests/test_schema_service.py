"""Service-level tests for schema engine edge cases."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate, AttributeUpdate
from app.schemas.entity import EntityCreate, EntityUpdate
from app.services.record_service import create_record, list_records
from app.services.schema_service import (
    SchemaError,
    add_attribute,
    create_entity,
    delete_attribute,
    entity_record_counts,
    get_entity_with_attributes,
    update_attribute,
    update_entity,
)


def test_update_entity_renames_but_keeps_slug(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    update_entity(db_session, entity, EntityUpdate(name="Server Renamed"))
    assert entity.name == "Server Renamed"
    assert entity.slug == "server"


def test_update_entity_duplicate_name_rejected(db_session):
    create_entity(db_session, EntityCreate(name="A"))
    b = create_entity(db_session, EntityCreate(name="B"))
    with pytest.raises(SchemaError):
        update_entity(db_session, b, EntityUpdate(name="A"))


def test_entity_record_counts(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    entity = get_entity_with_attributes(db_session, entity.id)
    create_record(db_session, entity, entity.attributes, {"name": "web01"})
    assert entity_record_counts(db_session) == {entity.id: 1}


def test_add_attribute_coerces_default(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Cores", data_type=DataType.INTEGER, default_value="4"),
    )
    assert attr.default_value == 4


def test_add_attribute_invalid_default_rejected(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    with pytest.raises(SchemaError):
        add_attribute(
            db_session,
            entity,
            AttributeCreate(name="Cores", data_type=DataType.INTEGER, default_value="abc"),
        )


def test_enum_default_must_be_an_option(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    with pytest.raises(SchemaError):
        add_attribute(
            db_session,
            entity,
            AttributeCreate(
                name="Status", data_type=DataType.ENUM, options=["a", "b"], default_value="c"
            ),
        )


def test_update_attribute_keeps_slug(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    update_attribute(db_session, attr, AttributeUpdate(name="Host", data_type=DataType.TEXT))
    assert attr.name == "Host"
    assert attr.slug == "hostname"


def test_delete_attribute_removes_value_from_records(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    extra = add_attribute(
        db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER)
    )
    entity = get_entity_with_attributes(db_session, entity.id)
    create_record(db_session, entity, entity.attributes, {"name": "web01", "cores": "8"})
    delete_attribute(db_session, extra)
    records = list_records(db_session, entity.id)
    assert "cores" not in records[0].data
