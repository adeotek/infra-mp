"""Service-level tests for view filtering, sorting, and CRUD."""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import create_record, list_records
from app.services.schema_service import (
    add_attribute,
    create_entity,
    get_entity_with_attributes,
    list_entities,
)
from app.services.view_service import (
    _sortable,
    apply_config,
    build_view_graph,
    build_view_rows,
    create_view,
    delete_view,
    filter_op_label,
    get_view,
    list_views,
    parse_column_spec,
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
    view = create_view(db_session, servers, "Active", {"columns": ["name"]}, icon="fa-bolt")
    assert view.name == "Active"
    assert view.icon == "fa-bolt"
    assert get_view(db_session, view.id) is view
    assert list_views(db_session) == [view]

    update_view(db_session, view, "Renamed", {"columns": ["cores"]}, icon="fa-cloud")
    assert get_view(db_session, view.id).name == "Renamed"
    assert view.icon == "fa-cloud"
    assert view.config == {"columns": ["cores"]}

    delete_view(db_session, view)
    assert get_view(db_session, view.id) is None
    assert list_views(db_session) == []


# --------------------------------------------------------------------------- #
# Related-entity columns (reference hops at any depth)
# --------------------------------------------------------------------------- #


@pytest.fixture
def ref_graph(db_session):
    """Site <- Rack <- Server -> NICs (many); records across all entities."""
    site = create_entity(db_session, EntityCreate(name="Site"))
    add_attribute(db_session, site, AttributeCreate(name="Name", data_type=DataType.TEXT))

    rack = create_entity(db_session, EntityCreate(name="Rack"))
    add_attribute(db_session, rack, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(
        db_session,
        rack,
        AttributeCreate(
            name="Site",
            data_type=DataType.REFERENCE,
            reference_entity_id=site.id,
            cardinality="one",
        ),
    )

    nic = create_entity(db_session, EntityCreate(name="NIC"))
    add_attribute(db_session, nic, AttributeCreate(name="IP", data_type=DataType.TEXT))

    server = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, server, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(
        db_session,
        server,
        AttributeCreate(
            name="Rack",
            data_type=DataType.REFERENCE,
            reference_entity_id=rack.id,
            cardinality="one",
        ),
    )
    add_attribute(
        db_session,
        server,
        AttributeCreate(
            name="NICs",
            data_type=DataType.REFERENCE,
            reference_entity_id=nic.id,
            cardinality="many",
        ),
    )

    def _reload(entity):
        loaded = get_entity_with_attributes(db_session, entity.id)
        assert loaded is not None
        return loaded

    site = _reload(site)
    rack = _reload(rack)
    nic = _reload(nic)
    server = _reload(server)

    s1 = create_record(db_session, site, site.attributes, {"name": "S1"})
    s2 = create_record(db_session, site, site.attributes, {"name": "S2"})
    r1 = create_record(db_session, rack, rack.attributes, {"name": "R1", "site": s1.id})
    r2 = create_record(db_session, rack, rack.attributes, {"name": "R2", "site": s2.id})
    n1 = create_record(db_session, nic, nic.attributes, {"ip": "10.0.0.1"})
    n2 = create_record(db_session, nic, nic.attributes, {"ip": "10.0.0.2"})
    n3 = create_record(db_session, nic, nic.attributes, {"ip": "10.0.0.3"})
    create_record(
        db_session,
        server,
        server.attributes,
        {
            "name": "A",
            "rack": r1.id,
            "nics": [n1.id, n2.id],
        },
    )
    create_record(
        db_session,
        server,
        server.attributes,
        {
            "name": "B",
            "rack": r2.id,
            "nics": [n3.id],
        },
    )
    create_record(db_session, server, server.attributes, {"name": "C"})
    create_record(db_session, server, server.attributes, {"name": "D", "nics": [n1.id, n2.id]})
    return {
        "site": site,
        "rack": rack,
        "nic": nic,
        "server": server,
        "entities": list_entities(db_session),
    }


def _cells(db, entity, config, key_slug="name"):
    records, columns = apply_config(
        entity,
        list_records(db, entity.id),
        config,
        list_entities(db),
    )
    rows = build_view_rows(db, entity, records, columns)
    out = {}
    for r in rows:
        row_key = r["record"].data.get(key_slug, f"#{r['record'].id}")
        out[row_key] = {c.key: r["cells"][c.key] for c in columns}
    return out


def test_related_column_up_one_hop(db_session, ref_graph):
    server, rack = ref_graph["server"], ref_graph["rack"]
    config = {
        "columns": [
            {"path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "first"}], "attr": "name"}
        ]
    }
    records, columns = apply_config(
        server,
        list_records(db_session, server.id),
        config,
        ref_graph["entities"],
    )
    assert [c.label for c in columns] == ["Rack › Name"]
    cells = _cells(db_session, server, config)
    assert cells["A"][columns[0].key] == "R1"
    assert cells["B"][columns[0].key] == "R2"
    assert cells["C"][columns[0].key] == "—"


def test_related_column_two_hops_up(db_session, ref_graph):
    server, rack, site = ref_graph["server"], ref_graph["rack"], ref_graph["site"]
    config = {
        "columns": [
            {
                "path": [
                    {"dir": "up", "ref": "rack", "to": rack.id, "many": "first"},
                    {"dir": "up", "ref": "site", "to": site.id, "many": "first"},
                ],
                "attr": "name",
            }
        ]
    }
    records, columns = apply_config(
        server,
        list_records(db_session, server.id),
        config,
        ref_graph["entities"],
    )
    assert [c.label for c in columns] == ["Rack › Site › Name"]
    cells = _cells(db_session, server, config)
    key = columns[0].key
    assert cells["A"][key] == "S1"
    assert cells["B"][key] == "S2"
    assert cells["C"][key] == "—"


def test_related_column_up_many_first(db_session, ref_graph):
    server, nic = ref_graph["server"], ref_graph["nic"]
    config = {
        "columns": [
            {"path": [{"dir": "up", "ref": "nics", "to": nic.id, "many": "first"}], "attr": "ip"}
        ]
    }
    cells = _cells(db_session, server, config)
    key = next(iter(cells["A"]))
    assert cells["A"][key] == "10.0.0.1"
    assert cells["B"][key] == "10.0.0.3"
    assert cells["C"][key] == "—"


def test_related_column_up_many_all_joins_values(db_session, ref_graph):
    server, nic = ref_graph["server"], ref_graph["nic"]
    config = {
        "columns": [
            {"path": [{"dir": "up", "ref": "nics", "to": nic.id, "many": "all"}], "attr": "ip"}
        ]
    }
    cells = _cells(db_session, server, config)
    key = next(iter(cells["A"]))
    assert cells["A"][key] == "10.0.0.1, 10.0.0.2"
    assert cells["D"][key] == "10.0.0.1, 10.0.0.2"
    assert cells["B"][key] == "10.0.0.3"
    assert cells["C"][key] == "—"


def test_related_column_down_one_hop(db_session, ref_graph):
    rack, server = ref_graph["rack"], ref_graph["server"]
    config = {
        "columns": [
            {
                "path": [{"dir": "down", "ref": "rack", "to": server.id, "many": "first"}],
                "attr": "name",
            }
        ]
    }
    cells = _cells(db_session, rack, config)
    key = next(iter(cells["R1"]))
    assert cells["R1"][key] == "A"
    assert cells["R2"][key] == "B"


def test_related_column_down_many_first_and_all(db_session, ref_graph):
    nic, server = ref_graph["nic"], ref_graph["server"]
    first_config = {
        "columns": [
            {
                "path": [{"dir": "down", "ref": "nics", "to": server.id, "many": "first"}],
                "attr": "name",
            }
        ]
    }
    all_config = {
        "columns": [
            {
                "path": [{"dir": "down", "ref": "nics", "to": server.id, "many": "all"}],
                "attr": "name",
            }
        ]
    }
    first_cells = _cells(db_session, nic, first_config, key_slug="ip")
    all_cells = _cells(db_session, nic, all_config, key_slug="ip")
    first_key = next(iter(first_cells["10.0.0.1"]))
    all_key = next(iter(all_cells["10.0.0.1"]))
    assert first_cells["10.0.0.1"][first_key] == "A"
    assert all_cells["10.0.0.1"][all_key] == "A, D"
    assert all_cells["10.0.0.3"][all_key] == "B"


def test_related_column_terminal_reference_uses_titles(db_session, ref_graph):
    server, rack = ref_graph["server"], ref_graph["rack"]
    config = {
        "columns": [
            {"path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "first"}], "attr": "site"}
        ]
    }
    cells = _cells(db_session, server, config)
    key = next(iter(cells["A"]))
    assert cells["A"][key] == "S1"
    assert cells["B"][key] == "S2"
    assert cells["C"][key] == "—"


def test_invalid_related_specs_are_skipped(db_session, ref_graph):
    server, rack = ref_graph["server"], ref_graph["rack"]
    config = {
        "columns": [
            "name",
            {
                "path": [{"dir": "up", "ref": "nope", "to": rack.id, "many": "first"}],
                "attr": "name",
            },
            {
                "path": [{"dir": "up", "ref": "rack", "to": 9999, "many": "first"}],
                "attr": "name",
            },
            {
                "path": [{"dir": "sideways", "ref": "rack", "to": rack.id, "many": "first"}],
                "attr": "name",
            },
            {
                "path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "sometimes"}],
                "attr": "name",
            },
            {
                "path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "first"}],
                "attr": "nope",
            },
            {"path": "garbage"},
        ]
    }
    records, columns = apply_config(
        server,
        list_records(db_session, server.id),
        config,
        ref_graph["entities"],
    )
    assert [c.key for c in columns] == ["name"]
    assert len(records) == 4


def test_parse_column_spec():
    assert parse_column_spec("base:name") == "name"
    assert parse_column_spec("rel:up:rack:3:first→name") == {
        "path": [{"dir": "up", "ref": "rack", "to": 3, "many": "first"}],
        "attr": "name",
    }
    assert parse_column_spec("rel:up:rack:3:first/down:nics:4:all→ip") == {
        "path": [
            {"dir": "up", "ref": "rack", "to": 3, "many": "first"},
            {"dir": "down", "ref": "nics", "to": 4, "many": "all"},
        ],
        "attr": "ip",
    }
    assert parse_column_spec("") is None
    assert parse_column_spec("base:") is None
    assert parse_column_spec("bogus") is None
    assert parse_column_spec("rel:up:rack:first→name") is None
    assert parse_column_spec("rel:up:rack:x:first→name") is None
    assert parse_column_spec("rel:up:rack:3:sometimes→name") is None
    assert parse_column_spec("rel:up:rack:3:first") is None


def test_build_view_graph(db_session, ref_graph):
    server, rack, nic = ref_graph["server"], ref_graph["rack"], ref_graph["nic"]
    graph = build_view_graph(db_session, server.id)
    assert graph["base"] == server.id
    server_node = graph["entities"][str(server.id)]
    assert [h["ref"] for h in server_node["up"]] == ["rack", "nics"]
    assert server_node["up"][0]["many"] is False
    assert server_node["up"][1]["many"] is True
    assert [h["ref"] for h in graph["entities"][str(rack.id)]["down"]] == ["rack"]
    assert [h["ref"] for h in graph["entities"][str(nic.id)]["down"]] == ["nics"]
    assert server_node["attrs"] == [
        {"slug": "name", "name": "Name"},
        {"slug": "rack", "name": "Rack"},
        {"slug": "nics", "name": "NICs"},
    ]
