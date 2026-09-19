"""Calculated view columns: formula engine, concatenation, and HTTP wiring.

Calculated columns are ordinary entries of a view's ``config["columns"]`` — dicts
carrying ``kind: concat`` or ``kind: formula`` — so they keep their place in the
column order and reorder alongside the standard columns. A separate
``config["calculated"]`` list (the older shape) still resolves, appended at the
end, which is where that shape always put them.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.calculated import (
    FormulaError,
    evaluate_formula,
    formula_references,
    parse_formula,
)
from app.services.record_service import create_record, list_records
from app.services.schema_service import (
    add_attribute,
    create_entity,
    get_entity_with_attributes,
    list_entities,
)
from app.services.view_service import apply_config, build_totals, build_view_rows


def _reload(db_session, entity):
    """get_entity_with_attributes returns Optional — assert and narrow."""
    loaded = get_entity_with_attributes(db_session, entity.id)
    assert loaded is not None
    return loaded


def _value(expr: str, values: dict | None = None):
    return evaluate_formula(parse_formula(expr), values or {})


# --------------------------------------------------------------------------- #
# Formula engine
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("expr", "values", "expected"),
    [
        ("1 + 2 * 3", {}, "7"),
        ("(1 + 2) * 3", {}, "9"),
        ("10 - 2 - 3", {}, "5"),
        ("100 / 8", {}, "12.5"),
        ("+5", {}, "5"),
        ("-{qty}", {"qty": 4}, "-4"),
        ("2 * -{qty}", {"qty": 3}, "-6"),
        ("{price} * {qty}", {"price": "10.25", "qty": 2}, "20.50"),
        ("{a} + {b} + {c}", {"a": 1, "b": 2, "c": 3}, "6"),
        ("round(2.5)", {}, "3"),
        ("round(2.44, 1)", {}, "2.4"),
        ("round(2.345, 2)", {}, "2.35"),
        ("round({price} / 3, 2)", {"price": "10"}, "3.33"),
        ("round({price} * {qty})", {"price": "1.5", "qty": 2}, "3"),
    ],
)
def test_formula_evaluation(expr, values, expected):
    value = _value(expr, values)
    assert value == Decimal(expected)
    assert isinstance(value, Decimal)


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "   ",
        "1 +",
        "* 2",
        "1 + 2)",
        "(1 + 2",
        "1 2",
        "max(1, 2)",
        "round 2",
        "round(1, 2",
        "round(1, 1.5)",
        "round(1, 99)",
        "1 % 2",
        "{}",
        "{unclosed",
        "1 & 2",
    ],
)
def test_formula_errors(expr):
    with pytest.raises(FormulaError):
        parse_formula(expr)


def test_formula_length_is_capped():
    with pytest.raises(FormulaError):
        parse_formula("1 + " * 100 + "1")


def test_formula_nesting_is_capped():
    with pytest.raises(FormulaError):
        parse_formula("(" * 40 + "1" + ")" * 40)


def test_missing_or_non_numeric_values_yield_none():
    assert _value("{a} + {b}", {"a": None, "b": 2}) is None
    assert _value("{a} + {b}", {"a": "text", "b": 2}) is None
    assert _value("{a} + {b}", {"a": True, "b": 2}) is None
    assert _value("{a} + {b}", {"b": 2}) is None


def test_division_by_zero_yields_none():
    assert _value("{a} / {b}", {"a": 1, "b": 0}) is None
    assert _value("1 / 0", {}) is None


def test_formula_references_lists_every_column():
    node = parse_formula("round({price} * {qty}, 2) + {price} - 1")
    assert formula_references(node) == {"price", "qty"}


# --------------------------------------------------------------------------- #
# Service level: concatenation and formulas over a real view
# --------------------------------------------------------------------------- #


@pytest.fixture
def shop(db_session):
    entity = create_entity(db_session, EntityCreate(name="Product"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, entity, AttributeCreate(name="Room", data_type=DataType.TEXT))
    add_attribute(db_session, entity, AttributeCreate(name="Price", data_type=DataType.DECIMAL))
    add_attribute(db_session, entity, AttributeCreate(name="Quantity", data_type=DataType.INTEGER))
    entity = _reload(db_session, entity)
    create_record(
        db_session,
        entity,
        entity.attributes,
        {"name": "Chair", "room": "A1", "price": "10.25", "quantity": 2},
    )
    create_record(
        db_session,
        entity,
        entity.attributes,
        {"name": "Table", "price": "99.50", "quantity": 1},
    )
    create_record(db_session, entity, entity.attributes, {"name": "Lamp"})
    return entity


def _by_name(rows):
    """Cells of each row keyed by the record's Name cell (order-independent)."""
    return {row["cells"]["name"]: row["cells"] for row in rows}


def _grid(db_session, entity, config):
    records, columns = apply_config(
        entity,
        list_records(db_session, entity.id),
        config,
        list_entities(db_session),
        db=db_session,
    )
    return columns, build_view_rows(db_session, entity, records, columns)


def test_concat_joins_cells_with_a_separator(db_session, shop):
    config = {
        "columns": ["name", "room"],
        "calculated": [
            {"kind": "concat", "label": "Where", "parts": ["name", "room"], "separator": " · "}
        ],
    }
    columns, rows = _grid(db_session, shop, config)
    assert [c.label for c in columns] == ["Name", "Room", "Where"]
    assert columns[-1].key == "calc:0"
    assert columns[-1].is_calculated is True
    assert columns[-1].is_numeric is False
    cells = _by_name(rows)
    assert cells["Chair"]["calc:0"] == "Chair · A1"
    # A missing part is dropped, not rendered as "— · …".
    assert cells["Table"]["calc:0"] == "Table"
    assert cells["Lamp"]["calc:0"] == "Lamp"


def test_concat_without_a_separator(db_session, shop):
    config = {
        "columns": ["name", "room"],
        "calculated": [{"kind": "concat", "label": "Code", "parts": ["name", "room"]}],
    }
    _, rows = _grid(db_session, shop, config)
    assert _by_name(rows)["Chair"]["calc:0"] == "ChairA1"


def test_concat_with_no_values_renders_the_dash(db_session, shop):
    config = {
        "columns": ["name", "room"],
        "calculated": [{"kind": "concat", "label": "R", "parts": ["room"]}],
    }
    _, rows = _grid(db_session, shop, config)
    cells = _by_name(rows)
    assert cells["Chair"]["calc:0"] == "A1"
    assert cells["Table"]["calc:0"] == "—"


def test_formula_column_computes_and_aligns_right(db_session, shop):
    config = {
        "columns": ["name", "price", "quantity"],
        "calculated": [
            {"kind": "formula", "label": "Total", "expr": "round({price} * {quantity}, 2)"}
        ],
    }
    columns, rows = _grid(db_session, shop, config)
    assert columns[-1].label == "Total"
    assert columns[-1].is_numeric is True
    cells = _by_name(rows)
    assert cells["Chair"]["calc:0"] == "20.5"
    assert cells["Table"]["calc:0"] == "99.5"
    # The third record has no price/quantity: nothing to compute.
    assert cells["Lamp"]["calc:0"] == "—"


def test_formula_can_mix_several_columns_and_constants(db_session, shop):
    config = {
        "columns": ["name", "price", "quantity"],
        "calculated": [
            {"kind": "formula", "label": "Discounted", "expr": "({price} * {quantity}) / 2 + 1"}
        ],
    }
    _, rows = _grid(db_session, shop, config)
    assert _by_name(rows)["Chair"]["calc:0"] == "11.25"


def test_second_calculated_column_can_use_another_column(db_session, shop):
    config = {
        "columns": ["name", "price"],
        "calculated": [
            {"kind": "concat", "label": "Label", "parts": ["name", "price"], "separator": ": "},
            {"kind": "formula", "label": "Ten times", "expr": "{price} * 10"},
        ],
    }
    columns, rows = _grid(db_session, shop, config)
    assert [c.key for c in columns][-2:] == ["calc:0", "calc:1"]
    chair = _by_name(rows)["Chair"]
    assert chair["calc:0"] == "Chair: 10.25"
    assert chair["calc:1"] == "102.5"


def test_broken_calculated_specs_are_skipped(db_session, shop):
    config = {
        "columns": ["price"],
        "calculated": [
            {"kind": "formula", "label": "Unknown ref", "expr": "{nope} * 2"},
            {"kind": "formula", "label": "Bad syntax", "expr": "1 +"},
            {"kind": "formula", "label": "No expression"},
            {"kind": "concat", "label": "No known parts", "parts": ["nope"]},
            {"kind": "concat", "label": "No parts"},
            {"kind": "nonsense", "label": "Bad kind"},
            {"label": "No kind"},
            "not a spec",
        ],
    }
    columns, rows = _grid(db_session, shop, config)
    assert [c.key for c in columns] == ["price"]
    assert "calc:0" not in rows[0]["cells"]


def test_calculated_columns_do_not_break_totals(db_session, shop):
    config = {
        "columns": ["name", "price"],
        "totals": {"price": "sum"},
        "calculated": [{"kind": "formula", "label": "Doubled", "expr": "{price} * 2"}],
    }
    columns, rows = _grid(db_session, shop, config)
    assert [c.key for c in columns] == ["name", "price", "calc:0"]
    assert _by_name(rows)["Chair"]["calc:0"] == "20.5"


def test_formula_over_a_related_column(db_session):
    supplier = create_entity(db_session, EntityCreate(name="Supplier"))
    add_attribute(db_session, supplier, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, supplier, AttributeCreate(name="Rebate", data_type=DataType.DECIMAL))
    product = create_entity(db_session, EntityCreate(name="Product"))
    add_attribute(db_session, product, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, product, AttributeCreate(name="Price", data_type=DataType.DECIMAL))
    add_attribute(
        db_session,
        product,
        AttributeCreate(
            name="Supplier",
            data_type=DataType.REFERENCE,
            reference_entity_id=supplier.id,
            cardinality="one",
        ),
    )
    supplier = _reload(db_session, supplier)
    product = _reload(db_session, product)
    acme = create_record(
        db_session, supplier, supplier.attributes, {"name": "Acme", "rebate": "2.5"}
    )
    create_record(
        db_session,
        product,
        product.attributes,
        {"name": "Chair", "price": "100", "supplier": acme.id},
    )
    rebate_key = f"rel:up:supplier:{supplier.id}:first→rebate"
    config = {
        "columns": [
            "price",
            {
                "path": [{"dir": "up", "ref": "supplier", "to": supplier.id, "many": "first"}],
                "attr": "rebate",
            },
        ],
        "calculated": [
            {"kind": "formula", "label": "Net", "expr": f"{{price}} - {{{rebate_key}}}"},
        ],
    }
    columns, rows = _grid(db_session, product, config)
    assert [c.key for c in columns] == ["price", rebate_key, "calc:0"]
    assert rows[0]["cells"]["calc:0"] == "97.5"


def test_concat_over_a_related_column(db_session):
    rack = create_entity(db_session, EntityCreate(name="Rack"))
    add_attribute(db_session, rack, AttributeCreate(name="Name", data_type=DataType.TEXT))
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
    rack = _reload(db_session, rack)
    server = _reload(db_session, server)
    rack_1 = create_record(db_session, rack, rack.attributes, {"name": "R1"})
    create_record(db_session, server, server.attributes, {"name": "web01", "rack": rack_1.id})
    rack_key = f"rel:up:rack:{rack.id}:first→name"
    config = {
        "columns": [
            "name",
            {
                "path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "first"}],
                "attr": "name",
            },
        ],
        "calculated": [
            {"kind": "concat", "label": "Location", "parts": [rack_key, "name"], "separator": "/"},
        ],
    }
    _, rows = _grid(db_session, server, config)
    assert rows[0]["cells"]["calc:0"] == "R1/web01"


# --------------------------------------------------------------------------- #
# HTTP wiring: view form, grid, CSV export, dashboard widget
# --------------------------------------------------------------------------- #


def _seed(client, login):
    login()
    client.post("/entities", data={"name": "Product"}, follow_redirects=False)
    for name, data_type in (("Name", "text"), ("Price", "decimal"), ("Qty", "integer")):
        client.post(
            "/entities/1/attributes",
            data={"name": name, "data_type": data_type},
            follow_redirects=False,
        )
    client.post(
        "/entities/1/records",
        data={"name": "Chair", "price": "10.25", "qty": "2"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/records",
        data={"name": "Table", "price": "99.50", "qty": "1"},
        follow_redirects=False,
    )


def _calc_row(payload: dict) -> str:
    return json.dumps(payload)


def _create_view(client, **extra):
    return client.post(
        "/views",
        data={
            "name": "V",
            "entity_id": "1",
            "col": ["base:name", "base:price", "base:qty"],
            **extra,
        },
        follow_redirects=False,
    )


def test_create_view_with_a_formula_column(client, login):
    _seed(client, login)
    resp = _create_view(
        client,
        calc=[
            _calc_row({"kind": "formula", "label": "Total", "expr": "round({price} * {qty}, 2)"})
        ],
    )
    assert resp.status_code == 303
    html = client.get("/views/1").text
    assert '<th class="num">Total</th>' in html
    assert "20.5" in html
    assert "99.5" in html


def test_create_view_with_a_concat_column(client, login):
    _seed(client, login)
    resp = _create_view(
        client,
        calc=[
            _calc_row(
                {"kind": "concat", "label": "Label", "parts": ["name", "price"], "separator": " — "}
            )
        ],
    )
    assert resp.status_code == 303
    html = client.get("/views/1").text
    assert "<th>Label</th>" in html
    assert "Chair — 10.25" in html


def test_concat_parts_must_reference_view_columns(client, login):
    _seed(client, login)
    resp = _create_view(
        client,
        col=["base:name"],
        calc=[_calc_row({"kind": "concat", "label": "X", "parts": ["nope"], "separator": ""})],
    )
    assert resp.status_code == 303
    assert "<th>X</th>" not in client.get("/views/1").text


def test_unknown_reference_in_a_formula_is_rejected(client, login):
    _seed(client, login)
    resp = _create_view(
        client, calc=[_calc_row({"kind": "formula", "label": "Bad", "expr": "{nope} * 2"})]
    )
    assert resp.status_code == 400
    assert (
        "is not one of the view&#39;s columns" in resp.text
        or "is not one of the view's columns" in resp.text
    )


def test_bad_formula_syntax_is_rejected(client, login):
    _seed(client, login)
    resp = _create_view(
        client, calc=[_calc_row({"kind": "formula", "label": "Bad", "expr": "1 +"})]
    )
    assert resp.status_code == 400
    assert "Unexpected" in resp.text or "ends unexpectedly" in resp.text


def test_edit_form_replays_the_calculated_columns(client, login):
    _seed(client, login)
    _create_view(
        client,
        calc=[_calc_row({"kind": "formula", "label": "Total", "expr": "{price} * {qty}"})],
    )
    html = client.get("/views/1/edit").text
    # The stored spec rides inside `columns` (one ordered list). The form also
    # still replays a legacy `calculated` list, so both keys are in the config.
    assert '"columns"' in html
    assert '"kind": "formula"' in html
    assert '"label": "Total"' in html
    assert '"expr": "{price} * {qty}"' in html
    assert 'id="calc-row-template"' in html


def test_update_view_keeps_calculated_columns(client, login):
    _seed(client, login)
    _create_view(
        client, calc=[_calc_row({"kind": "formula", "label": "Total", "expr": "{price} * {qty}"})]
    )
    resp = client.post(
        "/views/1/edit",
        data={
            "name": "V",
            "col": ["base:name", "base:price", "base:qty"],
            "calc": [
                _calc_row({"kind": "concat", "label": "Label", "parts": ["name"], "separator": ""})
            ],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    html = client.get("/views/1").text
    assert "<th>Label</th>" in html
    assert "<th>Total</th>" not in html


def test_csv_export_includes_calculated_columns(client, login):
    _seed(client, login)
    _create_view(
        client,
        calc=[
            _calc_row({"kind": "formula", "label": "Total", "expr": "round({price} * {qty}, 2)"})
        ],
    )
    body = client.get("/views/1/export").text.lstrip("\ufeff")
    assert body.splitlines()[0].endswith(",Total")
    assert "Chair,10.25,2,20.5" in body


def test_dashboard_widget_shows_calculated_columns(client, login):
    _seed(client, login)
    _create_view(
        client,
        calc=[
            _calc_row({"kind": "formula", "label": "Total", "expr": "round({price} * {qty}, 2)"})
        ],
    )
    client.post(
        "/dashboard/widgets",
        data={
            "title": "Products",
            "widget_type": "table",
            "entity_id": "1",
            "view_id": "1",
            "width": "6",
        },
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert '<th class="num">Total</th>' in html
    assert "20.5" in html


# --------------------------------------------------------------------------- #
# One ordered list: calculated columns reorder with the standard ones
# --------------------------------------------------------------------------- #


def _concat(label, parts, separator=""):
    return {"kind": "concat", "label": label, "parts": parts, "separator": separator}


def test_calculated_column_keeps_its_place_in_the_column_order(db_session, shop):
    config = {"columns": ["name", _concat("Where", ["name", "room"], " · "), "room"]}
    columns, rows = _grid(db_session, shop, config)
    assert [column.label for column in columns] == ["Name", "Where", "Room"]
    assert [column.key for column in columns] == ["name", "calc:0", "room"]
    assert _by_name(rows)["Chair"]["calc:0"] == "Chair · A1"


def test_calculated_column_can_reference_a_column_defined_after_it(db_session, shop):
    # The formula row comes first, `price`/`quantity` only later in the list.
    config = {
        "columns": [
            {"kind": "formula", "label": "Total", "expr": "{price} * {quantity}"},
            "name",
            "price",
            "quantity",
        ]
    }
    columns, rows = _grid(db_session, shop, config)
    assert [column.label for column in columns] == ["Total", "Name", "Price", "Quantity"]
    assert _by_name(rows)["Chair"]["calc:0"] == "20.5"


def test_reordering_the_specs_reorders_the_grid(db_session, shop):
    first = {"columns": ["name", _concat("Where", ["room"]), "room"]}
    second = {"columns": [_concat("Where", ["room"]), "room", "name"]}
    assert [c.label for c in _grid(db_session, shop, first)[0]] == ["Name", "Where", "Room"]
    assert [c.label for c in _grid(db_session, shop, second)[0]] == ["Where", "Room", "Name"]


def test_a_skipped_calculated_column_leaves_the_others_in_place(db_session, shop):
    config = {
        "columns": [
            "name",
            {"kind": "formula", "label": "Broken", "expr": "{nope} * 2"},
            _concat("Where", ["room"]),
            "room",
            "price",
        ]
    }
    columns, _ = _grid(db_session, shop, config)
    assert [column.label for column in columns] == ["Name", "Where", "Room", "Price"]


def test_legacy_calculated_list_still_appends_in_place_of_the_merged_row(db_session, shop):
    config = {
        "columns": ["name", "room"],
        "calculated": [_concat("Where", ["name", "room"])],
    }
    columns, _ = _grid(db_session, shop, config)
    assert [column.label for column in columns] == ["Name", "Room", "Where"]


def test_totals_are_keyed_by_column_not_by_position(db_session, shop):
    config = {
        "columns": [
            "room",
            _concat("Where", ["room"]),
            "price",
        ],
        "totals": {"price": "sum"},
    }
    columns, _ = _grid(db_session, shop, config)
    assert [column.label for column in columns] == ["Room", "Where", "Price"]
    totals = build_totals(db_session, shop, list_records(db_session, shop.id), columns, config)
    # The calculated column carries no total, the numeric one keeps its op even
    # though it is not the first column.
    assert list(totals) == ["price"]
    assert totals["price"]["op"] == "sum"
    assert totals["price"]["value"] == "109.75"


def test_view_form_submits_a_shared_order_for_both_row_kinds(client, login):
    _seed(client, login)
    resp = _create_view(
        client,
        col=["base:name", "base:price", "base:qty"],
        calc=[_calc_row({"kind": "formula", "label": "Total", "expr": "{price} * {qty}"})],
        col_order=["calc:0", "col:0", "col:1", "col:2"],
    )
    assert resp.status_code == 303
    html = client.get("/views/1").text
    assert html.index('<th class="num">Total</th>') < html.index("<th>Name</th>")
    assert html.index("<th>Name</th>") < html.index('<th class="num">Price</th>')
    assert html.index('<th class="num">Price</th>') < html.index('<th class="num">Qty</th>')


def test_submitted_order_is_stored_as_one_column_list(client, login):
    _seed(client, login)
    _create_view(
        client,
        col=["base:name", "base:price"],
        calc=[_calc_row(_concat("Where", ["name"]))],
        col_order=["col:0", "calc:0", "col:1"],
    )
    stored = client.get("/views/1/edit").text
    # `columns` carries the calculated spec in its submitted position and the
    # legacy key is gone: one list, one order.
    config_json = stored.split("var CONFIG = ", 1)[1].split(";\n", 1)[0]
    config = json.loads(config_json)
    assert config["columns"][0] == "name"
    assert config["columns"][1]["kind"] == "concat"
    assert config["columns"][2] == "price"
    assert "calculated" not in config


def test_grand_totals_survive_an_interleaved_calculated_row(client, login):
    _seed(client, login)
    _create_view(
        client,
        col=["base:name", "base:price"],
        col_total=["", "sum"],
        calc=[_calc_row(_concat("Where", ["name"]))],
        col_order=["calc:0", "col:0", "col:1"],
    )
    html = client.get("/views/1").text
    assert "109.75" in html  # 10.25 + 99.50, on the Price column


def test_view_form_lists_one_ordered_column_container(client, login):
    _seed(client, login)
    html = client.get("/views/new", params={"entity_id": 1}).text
    assert 'id="columns"' in html
    assert 'id="calculated"' not in html
    assert 'name="col_order"' in html
    assert html.count('id="calc-row-template"') == 1
    # Both row kinds are added to the same list, so ▲▼ and drag reorder across
    # them; the tokens keep the submitted order in sync with the DOM.
    assert "syncColumnOrder" in html
    assert 'class="row-move col-move" data-dir="up"' in html
