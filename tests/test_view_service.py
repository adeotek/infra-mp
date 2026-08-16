"""Service-level tests for view filtering, sorting, and CRUD."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import create_record, list_records
from app.services.schema_service import add_attribute, create_entity, get_entity_with_attributes
from app.services.view_service import (
    _sortable,
    apply_config,
    create_view,
    delete_view,
    filter_op_label,
    get_view,
    list_views,
    update_view,
)


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
        ("alpha", "4", "active"),
        ("bravo", "16", "retired"),
        ("charlie", None, "active"),  # Cores missing -> exercises null sorting/filtering
    ]:
        data = {"name": name, "status": status}
        if cores is not None:
            data["cores"] = cores
        create_record(db_session, entity, entity.attributes, data)
    return entity


def test_filter_neq(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "status", "op": "neq", "value": "active"}]},
    )
    assert [r.data["name"] for r in records] == ["bravo"]


def test_filter_is_null(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "cores", "op": "is_null"}]},
    )
    assert [r.data["name"] for r in records] == ["charlie"]


def test_filter_not_null(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "cores", "op": "not_null"}]},
    )
    assert {r.data["name"] for r in records} == {"alpha", "bravo"}


def test_filter_lt(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "cores", "op": "lt", "value": "8"}]},
    )
    assert [r.data["name"] for r in records] == ["alpha"]


def test_filter_gte_and_lte(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {
            "filters": [
                {"slug": "cores", "op": "gte", "value": "8"},
                {"slug": "cores", "op": "lte", "value": "16"},
            ]
        },
    )
    assert [r.data["name"] for r in records] == ["bravo"]


def test_filter_unknown_attribute_is_noop(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "nope", "op": "eq", "value": "x"}]},
    )
    assert len(records) == 3


def test_filter_gt_with_uncoercible_value_excludes(db_session, servers):
    # A numeric comparison against a non-numeric target raises TypeError and
    # excludes the record rather than crashing.
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"filters": [{"slug": "cores", "op": "gt", "value": "not-a-number"}]},
    )
    assert records == []


def test_sort_puts_none_last(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"sort": {"slug": "cores", "dir": "asc"}},
    )
    assert [r.data["name"] for r in records] == ["alpha", "bravo", "charlie"]


def test_sort_unknown_attribute_is_noop(db_session, servers):
    records, _ = apply_config(
        servers,
        list_records(db_session, servers.id),
        {"sort": {"slug": "nope", "dir": "desc"}},
    )
    assert len(records) == 3


def test_sortable_handles_bool_and_list():
    assert _sortable(True) == 1
    assert _sortable(False) == 0
    assert _sortable([1, 2]) == "[1, 2]"
    assert _sortable("x") == "x"


def test_filter_op_label():
    assert filter_op_label("eq") == "equals"
    assert filter_op_label("gte") == "greater or equal"
    assert filter_op_label("bogus") == "bogus"


def test_view_crud(db_session, servers):
    view = create_view(db_session, servers, "Active", {"columns": ["name"]})
    assert view.name == "Active"
    assert get_view(db_session, view.id) is view
    assert list_views(db_session) == [view]

    update_view(db_session, view, "Renamed", {"columns": ["cores"]})
    assert get_view(db_session, view.id).name == "Renamed"
    assert view.config == {"columns": ["cores"]}

    delete_view(db_session, view)
    assert get_view(db_session, view.id) is None
    assert list_views(db_session) == []
