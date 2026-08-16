"""Service-level tests for record display helpers."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import (
    best_effort_coerce,
    build_record_titles,
    build_rows,
    coerce_attribute_value,
    create_record,
    format_value,
    list_records,
    reference_options,
    resolve_reference_titles,
    title_attribute,
)
from app.services.schema_service import add_attribute, create_entity, get_entity_with_attributes
from app.services.validation import ValidationError


@pytest.fixture
def racks_and_servers(db_session):
    rack = create_entity(db_session, EntityCreate(name="Rack"))
    add_attribute(db_session, rack, AttributeCreate(name="Name", data_type=DataType.TEXT))
    server = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, server, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(
        db_session,
        server,
        AttributeCreate(name="Rack", data_type=DataType.REFERENCE, reference_entity_id=rack.id),
    )
    rack = get_entity_with_attributes(db_session, rack.id)
    server = get_entity_with_attributes(db_session, server.id)
    create_record(db_session, rack, rack.attributes, {"name": "Rack A"})
    create_record(db_session, server, server.attributes, {"name": "web01", "rack": "1"})
    return rack, server


def test_title_attribute_returns_first_text(db_session, racks_and_servers):
    _, server = racks_and_servers
    assert title_attribute(server.attributes).slug == "name"


def test_title_attribute_none_without_text(db_session):
    entity = create_entity(db_session, EntityCreate(name="E"))
    add_attribute(db_session, entity, AttributeCreate(name="N", data_type=DataType.INTEGER))
    entity = get_entity_with_attributes(db_session, entity.id)
    assert title_attribute(entity.attributes) is None


def test_build_record_titles(db_session, racks_and_servers):
    rack, _ = racks_and_servers
    titles = build_record_titles(db_session, rack.id)
    assert titles[1] == "Rack A"


def test_format_value():
    assert format_value(None) == "—"
    assert format_value(True) == "Yes"
    assert format_value(False) == "No"
    assert format_value([1, 2]) == "1, 2"
    assert format_value("x") == "x"


def test_resolve_reference_titles_and_build_rows(db_session, racks_and_servers):
    _, server = racks_and_servers
    titles = resolve_reference_titles(db_session, server)
    rows = build_rows(server, list_records(db_session, server.id), titles)
    assert len(rows) == 1
    assert rows[0]["cells"]["rack"] == "Rack A"


def test_reference_options(db_session, racks_and_servers):
    _, server = racks_and_servers
    options = reference_options(db_session, server)
    assert options["rack"] == [(1, "Rack A")]


def test_best_effort_coerce_preserves_invalid(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Status", data_type=DataType.ENUM, options=["a", "b"]),
    )
    entity = get_entity_with_attributes(db_session, entity.id)
    result = best_effort_coerce(entity.attributes, {"status": "bogus"})
    assert result["status"] == "bogus"


def test_coerce_enum_rejects_unknown_value(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Status", data_type=DataType.ENUM, options=["a", "b"]),
    )
    with pytest.raises(ValidationError):
        coerce_attribute_value(attr, "bogus")


def test_coerce_reference_rejects_non_numeric(db_session):
    rack = create_entity(db_session, EntityCreate(name="Rack"))
    server = create_entity(db_session, EntityCreate(name="Server"))
    attr = add_attribute(
        db_session,
        server,
        AttributeCreate(name="Rack", data_type=DataType.REFERENCE, reference_entity_id=rack.id),
    )
    with pytest.raises(ValidationError):
        coerce_attribute_value(attr, "not-a-number")
