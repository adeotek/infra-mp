"""Tests for the view filter/sort engine."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import create_record, list_records
from app.services.schema_service import add_attribute, create_entity, get_entity_with_attributes
from app.services.view_service import apply_config


@pytest.fixture
def servers(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER))
    add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Status", data_type=DataType.ENUM, options=["active", "retired"]),
    )
    entity = get_entity_with_attributes(db_session, entity.id)
    for name, cores, status in [
        ("alpha", 4, "active"),
        ("bravo", 16, "retired"),
        ("charlie", 8, "active"),
    ]:
        create_record(
            db_session,
            entity,
            entity.attributes,
            {"name": name, "cores": str(cores), "status": status},
        )
    return entity


def test_filter_equality(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "status", "op": "eq", "value": "active"}]},
    )
    assert len(records) == 2


def test_filter_greater_than(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "cores", "op": "gt", "value": "8"}]},
    )
    assert len(records) == 1
    assert records[0].data["name"] == "bravo"


def test_filter_contains(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "name", "op": "contains", "value": "arl"}]},
    )
    assert len(records) == 1
    assert records[0].data["name"] == "charlie"


def test_sort_descending(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"sort": {"slug": "name", "dir": "desc"}},
    )
    assert [r.data["name"] for r in records] == ["charlie", "bravo", "alpha"]


def test_column_subset(db_session, servers):
    records, columns = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"columns": ["name"]},
    )
    assert [c.slug for c in columns] == ["name"]
    assert len(records) == 3


def test_no_config_returns_all_records_and_columns(db_session, servers):
    records, columns = apply_config(servers, list_records(db_session, servers.id), {})
    assert len(records) == 3
    assert {c.slug for c in columns} == {"name", "cores", "status"}
