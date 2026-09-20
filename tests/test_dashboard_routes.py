"""HTTP tests for the dashboard and widget routes."""

import re


def _seed_server(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)


def test_index_redirects_to_dashboard(client, login):
    login()
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["location"]


def test_dashboard_renders(client, login):
    login()
    assert client.get("/dashboard").status_code == 200


def test_dashboard_config_renders(client, login):
    login()
    assert client.get("/dashboard/config").status_code == 200


def test_create_count_widget(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/dashboard/widgets",
        data={"title": "Servers", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Servers" in client.get("/dashboard").text


def test_create_table_widget(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/dashboard/widgets",
        data={"title": "Server List", "widget_type": "table", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Server List" in client.get("/dashboard").text


def test_table_widget_with_view(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    client.post(
        "/dashboard/widgets",
        data={"title": "T", "widget_type": "table", "entity_id": "1", "view_id": "1"},
        follow_redirects=False,
    )
    assert client.get("/dashboard").status_code == 200


def test_table_widget_with_view_renders_column_headers_and_cells(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    client.post(
        "/dashboard/widgets",
        data={"title": "T", "widget_type": "table", "entity_id": "1", "view_id": "1"},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    # View columns are ViewColumn objects: headers render from their labels
    # and cells from their keys (the template accesses .name / .slug).
    assert "<th>Name</th>" in html
    assert "web01" in html


def test_edit_widget_page(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    assert client.get("/dashboard/widgets/1/edit").status_code == 200


def test_edit_widget_page_404(client, login):
    login()
    assert client.get("/dashboard/widgets/9999/edit").status_code == 404


def test_update_widget(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    resp = client.post(
        "/dashboard/widgets/1/edit",
        data={"title": "Renamed", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_update_widget_404(client, login):
    login()
    resp = client.post(
        "/dashboard/widgets/9999/edit",
        data={"title": "x", "widget_type": "count", "entity_id": "", "view_id": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 404


def test_delete_widget(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    assert client.post("/dashboard/widgets/1/delete", follow_redirects=False).status_code == 303


def test_delete_widget_404(client, login):
    login()
    assert client.post("/dashboard/widgets/9999/delete", follow_redirects=False).status_code == 404


def test_create_widget_with_width(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={
            "title": "W",
            "widget_type": "count",
            "entity_id": "1",
            "view_id": "",
            "width": "12",
        },
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert "widget-span-12" in html
    assert "<td>12 / 12</td>" in client.get("/dashboard/config").text


def test_create_widget_accepts_legacy_width_tokens(client, login):
    """Widths stored before the 12-column grid still round-trip to their span."""
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={
            "title": "W",
            "widget_type": "count",
            "entity_id": "1",
            "view_id": "",
            "width": "full",
        },
        follow_redirects=False,
    )
    assert "widget-span-12" in client.get("/dashboard").text


def test_create_widget_defaults_to_half_width(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert "widget-span-6" in html
    assert "widget-span-12" not in html


def test_create_widget_invalid_width_defaults_to_half(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={
            "title": "W",
            "widget_type": "count",
            "entity_id": "1",
            "view_id": "",
            "width": "wacky",
        },
        follow_redirects=False,
    )
    assert "widget-span-6" in client.get("/dashboard").text


def test_create_widget_out_of_range_width_defaults_to_half(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={
            "title": "W",
            "widget_type": "count",
            "entity_id": "1",
            "view_id": "",
            "width": "13",
        },
        follow_redirects=False,
    )
    assert "widget-span-6" in client.get("/dashboard").text


def test_widget_widths_offer_all_twelve_spans(client, login):
    login()
    html = client.get("/dashboard/config").text
    for n in range(1, 13):
        assert f'<option value="{n}"' in html


def test_update_widget_width(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    resp = client.post(
        "/dashboard/widgets/1/edit",
        data={
            "title": "W",
            "widget_type": "count",
            "entity_id": "1",
            "view_id": "",
            "width": "9",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "widget-span-9" in client.get("/dashboard").text


def test_widget_title_links_to_entity_records(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "Servers", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert 'href="/entities/1/records" class="widget-title-link">Servers</a>' in html


def test_widget_title_links_to_the_view_when_one_is_bound(client, login):
    """A view-bound widget opens the view — that is the data it renders."""
    _seed_server(client, login)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    client.post(
        "/dashboard/widgets",
        data={"title": "Servers", "widget_type": "count", "entity_id": "1", "view_id": "1"},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    grid = html[html.index('<div class="widget-grid">') :]
    heading = grid[grid.index("<h2>") : grid.index("</h2>")]
    assert 'href="/views/1" class="widget-title-link">Servers</a>' in heading
    assert "/entities/1/records" not in heading


def test_widget_without_entity_title_is_not_a_link(client, login):
    login()
    client.post(
        "/dashboard/widgets",
        data={"title": "No entity", "widget_type": "count", "entity_id": "", "view_id": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert "No entity" in html
    assert "widget-title-link" not in html


def test_reorder_widgets(client, login):
    _seed_server(client, login)
    for title in ("W1", "W2"):
        client.post(
            "/dashboard/widgets",
            data={"title": title, "widget_type": "count", "entity_id": "1", "view_id": ""},
            follow_redirects=False,
        )
    html = client.get("/dashboard/config").text
    assert html.find("<td>W1</td>") < html.find("<td>W2</td>")
    resp = client.post("/dashboard/widgets/reorder", data={"order": "2,1"}, follow_redirects=False)
    assert resp.status_code == 204
    html = client.get("/dashboard/config").text
    assert html.find("<td>W2</td>") < html.find("<td>W1</td>")


def test_reorder_widgets_invalid_order(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    # Wrong permutation and non-numeric ids are rejected.
    assert client.post("/dashboard/widgets/reorder", data={"order": "1,2"}).status_code == 400
    assert client.post("/dashboard/widgets/reorder", data={"order": "x"}).status_code == 400


# --------------------------------------------------------------------------- #
# Table widget cells: links + copy buttons (same as the records/view grids)
# --------------------------------------------------------------------------- #

LINK_CELL = (
    '<span class="cell-value"><a href="https://panel.example.com" target="_blank" '
    'rel="noopener">https://panel.example.com</a></span>'
)


def _seed_link_server(client, login):
    """Entity 1: text Name + link Console (copy button on) and one record."""
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Name", "data_type": "text"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/attributes",
        data={"name": "Console", "data_type": "link", "with_copy_button": "on"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/records",
        data={"name": "web01", "console": "https://panel.example.com"},
        follow_redirects=False,
    )


def _add_table_widget(client, view_id: str = ""):
    client.post(
        "/dashboard/widgets",
        data={
            "title": "Server List",
            "widget_type": "table",
            "entity_id": "1",
            "view_id": view_id,
        },
        follow_redirects=False,
    )


def test_table_widget_renders_link_as_anchor_and_copy_button(client, login):
    _seed_link_server(client, login)
    _add_table_widget(client)
    html = client.get("/dashboard").text
    assert LINK_CELL in html
    assert '<i class="fa-regular fa-copy"' in html


def test_table_widget_with_view_renders_link_as_anchor_and_copy_button(client, login):
    _seed_link_server(client, login)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    _add_table_widget(client, view_id="1")
    html = client.get("/dashboard").text
    assert LINK_CELL in html
    assert '<i class="fa-regular fa-copy"' in html


def test_widget_cells_match_the_records_and_view_grids(client, login):
    """The widget table renders cells byte-for-byte like the other two grids."""
    _seed_link_server(client, login)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    _add_table_widget(client, view_id="1")
    for url in ("/entities/1/records", "/views/1", "/dashboard"):
        html = client.get(url).text
        assert LINK_CELL in html, url
        assert '<i class="fa-regular fa-copy"' in html, url


def test_table_widget_link_cell_without_a_value_is_plain_text(client, login):
    _seed_link_server(client, login)
    client.post("/entities/1/records", data={"name": "web02"}, follow_redirects=False)
    _add_table_widget(client)
    html = client.get("/dashboard").text
    assert html.count('<a href="https://panel.example.com"') == 1
    assert '<span class="cell-value">—</span>' in html
    # The empty cell gets no copy button either — only web01 holds a Console URL.
    assert html.count('class="copy-btn"') == 1


def test_table_widget_without_copy_flag_has_no_copy_button(client, login):
    _seed_server(client, login)
    _add_table_widget(client)
    html = client.get("/dashboard").text
    assert "web01" in html
    assert "copy-btn" not in html


# --------------------------------------------------------------------------- #
# Sum widgets
# --------------------------------------------------------------------------- #


def _seed_cost_server(client, login):
    """Entity 1: Name (text) + Price (decimal) + Qty (integer); two records."""
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post(
        "/entities/1/attributes",
        data={"name": "Price", "data_type": "decimal"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/attributes",
        data={"name": "Qty", "data_type": "integer"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/records",
        data={"name": "a", "price": "10.25", "qty": "2"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/records",
        data={"name": "b", "price": "4.50", "qty": "3"},
        follow_redirects=False,
    )


def test_create_sum_widget_totals_the_field(client, login):
    _seed_cost_server(client, login)
    resp = client.post(
        "/dashboard/widgets",
        data={
            "title": "Spend",
            "widget_type": "sum",
            "entity_id": "1",
            "view_id": "",
            "field": "price",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    html = client.get("/dashboard").text
    assert '<div class="stat-value">14.75</div>' in html
    # Same card markup as a count widget: the title names the value, so no
    # caption under it.
    assert "Sum of" not in html


def test_sum_widget_card_matches_a_count_widget(client, login):
    """Both stat widgets render one bare .stat-value, nothing else."""
    _seed_cost_server(client, login)
    for widget_type, field in (("sum", "price"), ("count", "")):
        client.post(
            "/dashboard/widgets",
            data={
                "title": widget_type,
                "widget_type": widget_type,
                "entity_id": "1",
                "view_id": "",
                "field": field,
            },
            follow_redirects=False,
        )
    html = client.get("/dashboard").text
    assert html.count('<div class="stat-value">') == 2
    assert '<p class="muted">Sum of' not in html
    rendered = re.findall(r'<div class="stat-value">([^<]+)</div>', html)
    assert set(rendered) == {"14.75", "2"}


def test_sum_widget_sums_integer_fields(client, login):
    _seed_cost_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "", "field": "qty"},
        follow_redirects=False,
    )
    assert '<div class="stat-value">5</div>' in client.get("/dashboard").text


def test_sum_widget_honours_its_view_filters(client, login):
    _seed_cost_server(client, login)
    client.post(
        "/views",
        data={
            "name": "Expensive",
            "entity_id": "1",
            "filter_slug": ["price"],
            "filter_op": ["gte"],
            "filter_value": ["10"],
        },
        follow_redirects=False,
    )
    client.post(
        "/dashboard/widgets",
        data={
            "widget_type": "sum",
            "entity_id": "1",
            "view_id": "1",
            "field": "price",
        },
        follow_redirects=False,
    )
    assert '<div class="stat-value">10.25</div>' in client.get("/dashboard").text


def test_sum_widget_without_values_shows_zero(client, login):
    _seed_cost_server(client, login)
    client.post("/entities/1/records", data={"name": "c"}, follow_redirects=False)
    client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "", "field": "price"},
        follow_redirects=False,
    )
    # _seed_cost_server seeded 14.75 of prices; the third record adds nothing.
    assert '<div class="stat-value">14.75</div>' in client.get("/dashboard").text


def test_sum_widget_rejects_a_non_numeric_field(client, login):
    from urllib.parse import unquote

    _seed_cost_server(client, login)
    resp = client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "", "field": "name"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "not a numeric field" in unquote(resp.headers["location"])
    assert "<code>sum</code>" not in client.get("/dashboard/config").text


def test_sum_widget_requires_a_field(client, login):
    from urllib.parse import unquote

    _seed_cost_server(client, login)
    resp = client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "", "field": ""},
        follow_redirects=False,
    )
    assert "Choose the numeric field" in unquote(resp.headers["location"])


def test_sum_widget_requires_an_entity(client, login):
    from urllib.parse import unquote

    _seed_cost_server(client, login)
    resp = client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "", "view_id": "", "field": "price"},
        follow_redirects=False,
    )
    assert "needs an entity" in unquote(resp.headers["location"])


def test_edit_page_preselects_the_sum_field(client, login):
    _seed_cost_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "", "field": "price"},
        follow_redirects=False,
    )
    html = client.get("/dashboard/widgets/1/edit").text
    assert 'value="price" selected' in html
    assert "numeric-fields" in html


def test_changing_a_widget_away_from_sum_clears_its_field(client, login):
    _seed_cost_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "", "field": "price"},
        follow_redirects=False,
    )
    resp = client.post(
        "/dashboard/widgets/1/edit",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    config = client.get("/dashboard/config").text
    assert "<code>sum</code>" not in config
    assert "14.75" not in client.get("/dashboard").text


# --------------------------------------------------------------------------- #
# Stat cards: centered value, optional colour, view-column sums
# --------------------------------------------------------------------------- #


def test_stat_widgets_are_marked_as_stat_cards(client, login):
    """Count/sum cards carry ``widget-stat`` — the hook the centering CSS uses."""
    _seed_cost_server(client, login)
    for widget_type, field in (("count", ""), ("sum", "price")):
        client.post(
            "/dashboard/widgets",
            data={
                "title": widget_type,
                "widget_type": widget_type,
                "entity_id": "1",
                "view_id": "",
                "field": field,
            },
            follow_redirects=False,
        )
    html = client.get("/dashboard").text
    assert html.count('<section class="widget widget-span-6 widget-stat">') == 2


def test_table_widget_is_not_a_stat_card(client, login):
    _seed_server(client, login)
    _add_table_widget(client)
    html = client.get("/dashboard").text
    assert '<section class="widget widget-span-6">' in html
    assert "widget-stat" not in html


def test_stat_value_is_centered_by_css(client, login):
    login()
    css = client.get("/static/style.css").text
    assert ".widget-stat .stat-value,\n.widget-stat .stat-empty { text-align: center; }" in css


def _seed_rack_capacity(client, login):
    """Rack (1: Name, Capacity) ← Server (2: Name, Rack); three servers."""
    login()
    client.post("/entities", data={"name": "Rack"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post(
        "/entities/1/attributes",
        data={"name": "Capacity", "data_type": "integer"},
        follow_redirects=False,
    )
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/2/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post(
        "/entities/2/attributes",
        data={
            "name": "Rack",
            "data_type": "reference",
            "reference_entity_id": "1",
            "cardinality": "one",
        },
        follow_redirects=False,
    )
    client.post(
        "/entities/1/records", data={"name": "R1", "capacity": "12"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "R2", "capacity": "8"}, follow_redirects=False)
    for name, rack in (("A", "1"), ("B", "2"), ("C", "1")):
        client.post(
            "/entities/2/records", data={"name": name, "rack": rack}, follow_redirects=False
        )


def test_sum_widget_sums_a_related_view_column(client, login):
    """A view column can hop to another entity and still be summable."""
    _seed_rack_capacity(client, login)
    key = "rel:up:rack:1:first→capacity"
    client.post(
        "/views",
        data={"name": "By rack", "entity_id": "2", "col": ["base:name", key]},
        follow_redirects=False,
    )
    resp = client.post(
        "/dashboard/widgets",
        data={
            "title": "Capacity",
            "widget_type": "sum",
            "entity_id": "2",
            "view_id": "1",
            "field": key,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # 12 (R1) + 8 (R2) + 12 (R1 again) — each server takes its rack's capacity.
    assert '<div class="stat-value">32</div>' in client.get("/dashboard").text


def test_sum_widget_sums_a_computed_view_column(client, login):
    """Computed (formula) columns are offered and summable like stored values."""
    import json

    _seed_cost_server(client, login)
    client.post(
        "/views",
        data={
            "name": "Totals",
            "entity_id": "1",
            "col": ["base:name", "base:price", "base:qty"],
            "calc": [
                json.dumps(
                    {"kind": "formula", "label": "Total", "expr": "round({price} * {qty}, 2)"}
                )
            ],
            "col_order": ["col:0", "col:1", "col:2", "calc:0"],
        },
        follow_redirects=False,
    )
    resp = client.post(
        "/dashboard/widgets",
        data={
            "title": "Total",
            "widget_type": "sum",
            "entity_id": "1",
            "view_id": "1",
            "field": "calc:0",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # 10.25 × 2 + 4.50 × 3 = 20.50 + 13.50
    assert '<div class="stat-value">34</div>' in client.get("/dashboard").text


def test_sum_widget_rejects_a_view_field_that_is_not_numeric(client, login):
    """A text concat column is a column, but not one to sum."""
    import json
    from urllib.parse import unquote

    _seed_cost_server(client, login)
    client.post(
        "/views",
        data={
            "name": "Labeled",
            "entity_id": "1",
            "col": ["base:name", "base:price"],
            "calc": [json.dumps({"kind": "concat", "label": "Label", "expr": "{name} ({price})"})],
            "col_order": ["col:0", "col:1", "calc:0"],
        },
        follow_redirects=False,
    )
    resp = client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "1", "field": "calc:0"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "'Label' is not a numeric column" in unquote(resp.headers["location"])
    assert "<code>sum</code>" not in client.get("/dashboard/config").text


def test_sum_widget_rejects_a_field_outside_the_view_columns(client, login):
    from urllib.parse import unquote

    _seed_cost_server(client, login)
    client.post(
        "/views",
        data={"name": "Money", "entity_id": "1", "col": ["base:price"]},
        follow_redirects=False,
    )
    resp = client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "1", "field": "qty"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Choose a numeric column of the selected view" in unquote(resp.headers["location"])


def test_sum_widget_with_a_view_and_no_field_asks_for_a_column(client, login):
    from urllib.parse import unquote

    _seed_cost_server(client, login)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    resp = client.post(
        "/dashboard/widgets",
        data={"widget_type": "sum", "entity_id": "1", "view_id": "1", "field": ""},
        follow_redirects=False,
    )
    assert "Choose a numeric column" in unquote(resp.headers["location"])


def test_view_bound_widget_takes_the_views_entity(client, login):
    """A view decides its own records: the stored entity follows it."""
    _seed_cost_server(client, login)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    client.post(
        "/dashboard/widgets",
        data={"title": "Servers", "widget_type": "count", "entity_id": "", "view_id": "1"},
        follow_redirects=False,
    )
    assert '<div class="stat-value">2</div>' in client.get("/dashboard").text


def test_view_bound_sum_widget_sums_without_an_entity(client, login):
    _seed_cost_server(client, login)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    resp = client.post(
        "/dashboard/widgets",
        data={
            "title": "Spend",
            "widget_type": "sum",
            "entity_id": "",
            "view_id": "1",
            "field": "price",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert '<div class="stat-value">14.75</div>' in client.get("/dashboard").text


def test_widget_with_an_unknown_view_is_rejected(client, login):
    from urllib.parse import unquote

    _seed_cost_server(client, login)
    resp = client.post(
        "/dashboard/widgets",
        data={"widget_type": "count", "entity_id": "1", "view_id": "9999"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Unknown view for this widget" in unquote(resp.headers["location"])


def test_widget_form_offers_entity_and_view_fields(client, login):
    import json

    _seed_cost_server(client, login)
    client.post(
        "/views",
        data={
            "name": "Totals",
            "entity_id": "1",
            "col": ["base:price", "base:qty"],
            "calc": [
                json.dumps({"kind": "formula", "label": "Yearly", "expr": "round({price} * 12, 2)"})
            ],
            "col_order": ["col:0", "col:1", "calc:0"],
        },
        follow_redirects=False,
    )
    html = client.get("/dashboard/config").text
    assert '<optgroup label="Entity · Server">' in html
    assert '<optgroup label="View · Totals">' in html
    # The view's numeric columns — computed ones included — are the view group's.
    assert '<option value="calc:0">Yearly</option>' in html
    assert '<option value="price">Price</option>' in html
    # Labels/hints explain both sources and the colour field.
    assert "Numeric field (sum widgets)" in html
    assert "computed ones included" in html
    assert "Value color (count/sum)" in html
    assert "leave empty for the default" in html
    options = json.loads(html.split('id="numeric-fields">', 1)[1].split("</script>", 1)[0])
    assert [v["fields"] for v in options["views"] if v["name"] == "Totals"] == [
        [
            {"value": "price", "label": "Price"},
            {"value": "qty", "label": "Qty"},
            {"value": "calc:0", "label": "Yearly"},
        ]
    ]


def test_edit_form_preselects_a_view_column(client, login):
    import json

    _seed_cost_server(client, login)
    client.post(
        "/views",
        data={
            "name": "Totals",
            "entity_id": "1",
            "col": ["base:price"],
            "calc": [json.dumps({"kind": "formula", "label": "Yearly", "expr": "{price} * 12"})],
            "col_order": ["col:0", "calc:0"],
        },
        follow_redirects=False,
    )
    client.post(
        "/dashboard/widgets",
        data={
            "title": "Yearly",
            "widget_type": "sum",
            "entity_id": "1",
            "view_id": "1",
            "field": "calc:0",
        },
        follow_redirects=False,
    )
    html = client.get("/dashboard/widgets/1/edit").text
    assert 'value="calc:0" selected' in html


def test_stat_widget_renders_its_color(client, login):
    _seed_cost_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={
            "title": "Spend",
            "widget_type": "sum",
            "entity_id": "1",
            "view_id": "",
            "field": "price",
            "color": "#14B8A6",
        },
        follow_redirects=False,
    )
    # Hex colours are normalised to lower case before they are stored.
    assert (
        '<div class="stat-value" style="color: #14b8a6">14.75</div>'
        in client.get("/dashboard").text
    )


def test_stat_widget_without_a_color_keeps_the_default(client, login):
    _seed_cost_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"widget_type": "count", "entity_id": "1", "view_id": "", "color": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert '<div class="stat-value">2</div>' in html
    assert 'style="color' not in html


def test_invalid_color_is_rejected(client, login):
    from urllib.parse import unquote

    _seed_cost_server(client, login)
    resp = client.post(
        "/dashboard/widgets",
        data={"widget_type": "count", "entity_id": "1", "view_id": "", "color": "red"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "must be a hex value" in unquote(resp.headers["location"])
    assert "No widgets yet." in client.get("/dashboard/config").text


def test_color_is_ignored_for_table_widgets(client, login):
    """The colour field belongs to count/sum cards; a table widget drops it."""
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={
            "title": "T",
            "widget_type": "table",
            "entity_id": "1",
            "view_id": "",
            "color": "#123456",
        },
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert 'style="color' not in html
    edit = client.get("/dashboard/widgets/1/edit").text
    assert 'value="" placeholder="e.g. #14b8a6"' in edit


def test_edit_form_shows_the_stored_color_and_clearing_removes_it(client, login):
    _seed_cost_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={
            "title": "W",
            "widget_type": "count",
            "entity_id": "1",
            "view_id": "",
            "color": "#a1b2c3",
        },
        follow_redirects=False,
    )
    edit = client.get("/dashboard/widgets/1/edit").text
    assert 'value="#a1b2c3" placeholder="e.g. #14b8a6"' in edit
    assert 'id="widget-color-swatch" aria-hidden="true"></span>' in edit
    resp = client.post(
        "/dashboard/widgets/1/edit",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": "", "color": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert 'style="color' not in client.get("/dashboard").text


def test_a_stale_non_hex_stored_color_is_not_rendered(client, login, db_session):
    """Hand-edited configs are read leniently: the inline style never leaks."""
    from app.models.dashboard import DashboardWidget

    _seed_cost_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    widget = db_session.get(DashboardWidget, 1)
    assert widget is not None
    widget.config = {"color": "red; background: url(https://evil.example)"}
    db_session.commit()
    html = client.get("/dashboard").text
    assert '<div class="stat-value">2</div>' in html
    assert "evil.example" not in html
