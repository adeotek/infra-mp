"""Tests for the schema engine (entities and attributes)."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.schema_service import (
    SchemaError,
    add_attribute,
    create_entity,
    delete_entity,
    get_entity_with_attributes,
)


def test_create_entity_generates_slug(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server Rack"))
    assert entity.slug == "server-rack"


def test_duplicate_entity_name_is_rejected(db_session):
    create_entity(db_session, EntityCreate(name="Server"))
    with pytest.raises(SchemaError):
        create_entity(db_session, EntityCreate(name="Server"))


def test_slug_collisions_get_unique_slugs(db_session):
    e1 = create_entity(db_session, EntityCreate(name="Server"))
    e2 = create_entity(db_session, EntityCreate(name="Server!"))  # different name, same slug base
    assert e1.slug == "server"
    assert e2.slug == "server-2"


def test_entity_slug_is_ascii_only(db_session):
    entity = create_entity(db_session, EntityCreate(name="Réseau — Équipement"))
    assert entity.slug == "reseau-equipement"


def test_add_text_attribute(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT)
    )
    assert attr.slug == "hostname"
    assert attr.data_type == "text"


def test_add_enum_attribute_stores_options(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Status", data_type=DataType.ENUM, options=["active", "retired"]),
    )
    assert attr.config["options"] == ["active", "retired"]


def test_enum_requires_at_least_two_options(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    with pytest.raises(SchemaError):
        add_attribute(db_session, entity, AttributeCreate(name="Bad", data_type=DataType.ENUM))


def test_reference_requires_target(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    with pytest.raises(SchemaError):
        add_attribute(
            db_session, entity, AttributeCreate(name="Rack", data_type=DataType.REFERENCE)
        )


def test_reference_to_missing_entity_fails(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    with pytest.raises(SchemaError):
        add_attribute(
            db_session,
            entity,
            AttributeCreate(name="Rack", data_type=DataType.REFERENCE, reference_entity_id=9999),
        )


def test_add_reference_attribute(db_session):
    rack = create_entity(db_session, EntityCreate(name="Rack"))
    server = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        server,
        AttributeCreate(name="Rack", data_type=DataType.REFERENCE, reference_entity_id=rack.id),
    )
    assert attr.config["cardinality"] == "one"
    assert attr.config["reference_entity_id"] == rack.id


def test_delete_entity_cascades(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    delete_entity(db_session, entity)
    assert get_entity_with_attributes(db_session, entity.id) is None
