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
