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
    apply_config,
    build_totals,
    build_view_graph,
    build_view_rows,
    create_view,
    delete_view,
    filter_op_label,
    get_view,
    list_views,
    parse_column_spec,
    sort_value,
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


def test_sort_value_handles_mixed_types():
    """Typed sort keys never raise on mixed legacy data (bools/numbers/text)."""
    from decimal import Decimal

    assert sort_value(True) == (0, 1, "")
    assert sort_value(False) == (0, 0, "")
    assert sort_value(5) == (1, Decimal("5"), "")
    assert sort_value("10") == (1, Decimal("10"), "")
    assert sort_value(2.5) == (1, Decimal("2.5"), "")
    assert sort_value([1, 2]) == (2, 0, "[1, 2]")
    assert sort_value("x") == (2, 0, "x")
    # Ordering across types is stable: bool < number < text.
    keys = [sort_value(v) for v in ["x", 5, True, "2"]]
    assert sorted(keys) == [sort_value(True), sort_value("2"), sort_value(5), sort_value("x")]


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


def test_sort_by_related_column(db_session, ref_graph):
    server, rack = ref_graph["server"], ref_graph["rack"]
    sort_col = {
        "path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "first"}],
        "attr": "name",
    }
    config = {
        "columns": [sort_col],
        "sort": {"col": sort_col, "dir": "desc"},
    }
    records, _ = apply_config(
        server,
        list_records(db_session, server.id),
        config,
        list_entities(db_session),
        db=db_session,
    )
    # B -> R2, A -> R1, C and D have no rack (value-less records last,
    # keeping their relative order: D is the most recent record).
    assert [r.data["name"] for r in records] == ["B", "A", "D", "C"]


def test_sort_by_related_many_column_uses_first_value(db_session, ref_graph):
    server, nic = ref_graph["server"], ref_graph["nic"]
    sort_col = {
        "path": [{"dir": "up", "ref": "nics", "to": nic.id, "many": "first"}],
        "attr": "ip",
    }
    config = {
        "columns": [sort_col],
        "sort": {"col": sort_col, "dir": "asc"},
    }
    records, _ = apply_config(
        server,
        list_records(db_session, server.id),
        config,
        list_entities(db_session),
        db=db_session,
    )
    # D and A both start with 10.0.0.1 (stable order D, A — D is newest),
    # B has 10.0.0.3, C has none and goes last.
    assert [r.data["name"] for r in records] == ["D", "A", "B", "C"]


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
        {"slug": "name", "name": "Name", "type": "text"},
        {"slug": "rack", "name": "Rack", "type": "reference"},
        {"slug": "nics", "name": "NICs", "type": "reference"},
    ]


def test_sort_value_treats_non_finite_as_text():
    # Legacy rows (pre-v0.7.1) and plain text attributes may hold non-finite
    # numeric strings; sorting them must never raise during comparison.
    assert sort_value("NaN")[0] == 2
    assert sort_value("Infinity")[0] == 2
    assert sort_value("-Infinity")[0] == 2
    assert sort_value(float("nan"))[0] == 2
    assert sort_value(float("inf"))[0] == 2
    # Finite values still sort numerically, including huge exponents.
    assert sort_value("1e999999999")[0] == 1
    # Mixed finite/non-finite sort completes and non-finite values go last.
    assert sorted(["NaN", "2", "10"], key=sort_value) == ["2", "10", "NaN"]


@pytest.fixture
def link_graph(db_session):
    """Panel/Rack <- Server link graph for link-column href resolution."""
    panel = create_entity(db_session, EntityCreate(name="Panel"))
    add_attribute(db_session, panel, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, panel, AttributeCreate(name="URL", data_type=DataType.LINK))

    rack = create_entity(db_session, EntityCreate(name="Rack"))
    add_attribute(db_session, rack, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, rack, AttributeCreate(name="Panel", data_type=DataType.LINK))

    server = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, server, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, server, AttributeCreate(name="Console", data_type=DataType.LINK))
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
            name="Panels",
            data_type=DataType.REFERENCE,
            reference_entity_id=panel.id,
            cardinality="many",
        ),
    )

    def _reload(entity):
        loaded = get_entity_with_attributes(db_session, entity.id)
        assert loaded is not None
        return loaded

    panel, rack, server = _reload(panel), _reload(rack), _reload(server)
    p1 = create_record(
        db_session, panel, panel.attributes, {"name": "P1", "url": "https://p1.example.com"}
    )
    p2 = create_record(
        db_session, panel, panel.attributes, {"name": "P2", "url": "https://p2.example.com"}
    )
    r1 = create_record(
        db_session, rack, rack.attributes, {"name": "R1", "panel": "https://panel.example.com"}
    )
    create_record(db_session, rack, rack.attributes, {"name": "R2"})
    create_record(
        db_session,
        server,
        server.attributes,
        {"name": "A", "console": "https://console-a.example.com", "rack": r1.id, "panels": [p1.id]},
    )
    create_record(
        db_session,
        server,
        server.attributes,
        {"name": "B", "rack": 2, "panels": [p1.id, p2.id]},
    )
    create_record(db_session, server, server.attributes, {"name": "C"})
    return {"panel": panel, "rack": rack, "server": server}


def _rows_by_name(db, entity, config):
    records, columns = apply_config(
        entity, list_records(db, entity.id), config, list_entities(db), db=db
    )
    rows = build_view_rows(db, entity, records, columns)
    return {r["record"].data.get("name"): r for r in rows}, columns


def test_base_link_column_provides_hrefs(db_session, link_graph):
    server = link_graph["server"]
    rows, _ = _rows_by_name(db_session, server, {})
    assert rows["A"]["cells"]["console"] == "https://console-a.example.com"
    assert rows["A"]["link_hrefs"]["console"] == "https://console-a.example.com"
    # Non-link and empty cells carry no href.
    assert "name" not in rows["A"]["link_hrefs"]
    assert "console" not in rows["B"]["link_hrefs"]  # B has no console URL


def test_related_link_column_provides_href(db_session, link_graph):
    server, rack = link_graph["server"], link_graph["rack"]
    config = {
        "columns": [
            {
                "path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "first"}],
                "attr": "panel",
            }
        ]
    }
    rows, columns = _rows_by_name(db_session, server, config)
    key = columns[0].key
    assert rows["A"]["cells"][key] == "https://panel.example.com"
    assert rows["A"]["link_hrefs"][key] == "https://panel.example.com"
    # R2 has no panel URL -> dash, no link.
    assert rows["B"]["cells"][key] == "—"
    assert key not in rows["B"]["link_hrefs"]


def test_related_link_column_many_all_is_plain_text(db_session, link_graph):
    server, panel = link_graph["server"], link_graph["panel"]
    config = {
        "columns": [
            {"path": [{"dir": "up", "ref": "panels", "to": panel.id, "many": "all"}], "attr": "url"}
        ]
    }
    rows, columns = _rows_by_name(db_session, server, config)
    key = columns[0].key
    # Two URLs joined -> no single link target.
    assert rows["B"]["cells"][key] == "https://p1.example.com, https://p2.example.com"
    assert key not in rows["B"]["link_hrefs"]
    # Exactly one reached URL -> linkable.
    assert rows["A"]["cells"][key] == "https://p1.example.com"
    assert rows["A"]["link_hrefs"][key] == "https://p1.example.com"


# --------------------------------------------------------------------------- #
# Grand totals
# --------------------------------------------------------------------------- #


@pytest.fixture
def costs(db_session):
    """Servers with a decimal Price and integer Cores; one row without a price."""
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER))
    add_attribute(db_session, entity, AttributeCreate(name="Price", data_type=DataType.DECIMAL))
    entity = get_entity_with_attributes(db_session, entity.id)
    for name, cores, price in [("a", 4, "1200.50"), ("b", 16, "0.50"), ("c", 10, "5")]:
        create_record(
            db_session, entity, entity.attributes, {"name": name, "cores": cores, "price": price}
        )
    return entity


def _totals(db_session, entity, config):
    records, columns = apply_config(
        entity,
        list_records(db_session, entity.id),
        config,
        list_entities(db_session),
        db=db_session,
    )
    return build_totals(db_session, entity, records, columns, config)


def test_totals_sum_min_max_avg(db_session, costs):
    assert _totals(db_session, costs, {"totals": {"cores": "sum"}}) == {
        "cores": {"op": "sum", "value": "30"}
    }
    assert _totals(db_session, costs, {"totals": {"cores": "min"}})["cores"]["value"] == "4"
    assert _totals(db_session, costs, {"totals": {"cores": "max"}})["cores"]["value"] == "16"
    assert _totals(db_session, costs, {"totals": {"cores": "avg"}})["cores"]["value"] == "10"


def test_totals_format_with_separators_and_no_trailing_zeros(db_session, costs):
    totals = _totals(db_session, costs, {"totals": {"price": "sum"}})
    assert totals["price"] == {"op": "sum", "value": "1,206"}
    assert _totals(db_session, costs, {"totals": {"price": "avg"}})["price"]["value"] == "402"
    assert _totals(db_session, costs, {"totals": {"price": "min"}})["price"]["value"] == "0.5"
    assert _totals(db_session, costs, {"totals": {"price": "max"}})["price"]["value"] == "1,200.5"


def test_totals_follow_the_view_filters(db_session, costs):
    config = {
        "filters": [{"col": "cores", "op": "gte", "value": "10"}],
        "totals": {"cores": "sum"},
    }
    assert _totals(db_session, costs, config)["cores"]["value"] == "26"


def test_totals_skip_non_numeric_and_unknown_ops(db_session, costs):
    config = {"totals": {"name": "sum", "cores": "median", "missing": "sum"}}
    assert _totals(db_session, costs, config) == {}


def test_totals_empty_result_has_no_entry(db_session, costs):
    config = {
        "filters": [{"col": "name", "op": "eq", "value": "nothing"}],
        "totals": {"cores": "sum"},
    }
    assert _totals(db_session, costs, config) == {}


def test_totals_without_config_are_empty(db_session, costs):
    assert _totals(db_session, costs, {}) == {}


def test_totals_over_a_related_column(db_session):
    rack = create_entity(db_session, EntityCreate(name="Rack"))
    add_attribute(db_session, rack, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, rack, AttributeCreate(name="Capacity", data_type=DataType.INTEGER))
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
    rack = get_entity_with_attributes(db_session, rack.id)
    server = get_entity_with_attributes(db_session, server.id)
    r1 = create_record(db_session, rack, rack.attributes, {"name": "R1", "capacity": 10})
    r2 = create_record(db_session, rack, rack.attributes, {"name": "R2", "capacity": 4})
    for name, target in [("a", r1.id), ("b", r1.id), ("c", r2.id)]:
        create_record(db_session, server, server.attributes, {"name": name, "rack": target})

    config = {
        "columns": [
            {
                "path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "first"}],
                "attr": "capacity",
            }
        ],
    }
    records, columns = apply_config(
        server,
        list_records(db_session, server.id),
        config,
        list_entities(db_session),
        db=db_session,
    )
    key = columns[0].key
    totals = build_totals(db_session, server, records, columns, {**config, "totals": {key: "sum"}})
    assert totals[key]["value"] == "24"
