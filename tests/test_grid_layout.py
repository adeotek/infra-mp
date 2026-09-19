"""Grid layout: the actions column leads every data grid, numeric columns
align right, and the sticky horizontal scrollbar ships with its CSS/JS.

Action-column order matters because the grids are sorted client-side: index
comparisons on the served HTML are the cheapest way to pin the column order
down without a browser.
"""

import json


def _seed(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    client.post("/views", data={"name": "All", "entity_id": "1"}, follow_redirects=False)
    client.post("/users", data={"username": "ved", "password": "pw-123456"}, follow_redirects=False)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )


def test_records_grid_actions_column_is_first(client, login):
    _seed(client, login)
    html = client.get("/entities/1/records").text
    thead = html[html.index("<thead>") : html.index("</thead>")]
    assert thead.index('class="no-sort"') < thead.index("<th>Name</th>")
    body = html[html.index("<tbody>") :]
    assert body.index('class="row-actions"') < body.index('class="cell-value"')


def test_entities_grid_actions_column_is_first(client, login):
    _seed(client, login)
    html = client.get("/entities").text
    assert html.index('<th class="no-sort">') < html.index("<th>Name</th>")
    assert html.index('class="row-actions"') < html.index('href="/entities/1"')


def test_users_grid_actions_column_is_first(client, login):
    _seed(client, login)
    html = client.get("/users").text
    assert html.index('<th class="no-sort">') < html.index("<th>Username</th>")


def test_views_grid_actions_column_is_first(client, login):
    _seed(client, login)
    html = client.get("/views").text
    assert html.index('<th class="no-sort">') < html.index("<th>Name</th>")


def test_entity_detail_actions_column_precedes_the_data(client, login):
    _seed(client, login)
    html = client.get("/entities/1").text
    table = html[html.index('<table class="table" id="attributes-table"') :]
    thead = table[: table.index("</thead>")]
    # The drag handle keeps the very first column; the actions column follows
    # it and precedes every data column.
    assert thead.index("drag-handle-col") < thead.index('<th class="no-sort"></th><th>Name</th>')
    body = table[table.index("<tbody>") :]
    assert body.index('class="row-actions"') < body.index("<td>Name")


def test_dashboard_config_actions_column_precedes_the_data(client, login):
    _seed(client, login)
    html = client.get("/dashboard/config").text
    table = html[html.index('<table class="table" id="widgets-table"') :]
    thead = table[: table.index("</thead>")]
    assert thead.index('class="no-sort"') < thead.index("<th>Title</th>")
    body = table[table.index("<tbody>") :]
    assert body.index('class="row-actions"') < body.index("<td>W</td>")


def test_sticky_scrollbar_ships_with_css_and_js(client, login):
    login()
    css = client.get("/static/style.css").text
    js = client.get("/static/app.js").text
    assert ".sticky-scrollbar" in css
    assert ".sticky-scrollbar.visible" in css
    assert "initStickyScrollbar" in js
    assert "updateStickyScrollbars" in js


def test_widget_grid_has_twelve_spans(client, login):
    login()
    css = client.get("/static/style.css").text
    assert "grid-template-columns: repeat(12, 1fr)" in css
    for n in range(1, 13):
        assert f".widget-span-{n} " in css


# --------------------------------------------------------------------------- #
# Numeric columns align right (records grids, custom views, widget grids)
# --------------------------------------------------------------------------- #


def _seed_numeric(client, login):
    """Entity 1: text Name + integer Cores + decimal Price, one record."""
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    for name, data_type in (("Name", "text"), ("Cores", "integer"), ("Price", "decimal")):
        client.post(
            "/entities/1/attributes",
            data={"name": name, "data_type": data_type},
            follow_redirects=False,
        )
    client.post(
        "/entities/1/records",
        data={"name": "web01", "cores": "8", "price": "10.25"},
        follow_redirects=False,
    )


def test_records_grid_aligns_numeric_columns(client, login):
    _seed_numeric(client, login)
    html = client.get("/entities/1/records").text
    table = html[html.index('<table class="table" id="records-table"') :]
    thead = table[: table.index("</thead>")]
    assert '<th class="num">Cores</th>' in thead
    assert '<th class="num">Price</th>' in thead
    assert "<th>Name</th>" in thead
    assert "<th>Cores</th>" not in thead.replace('<th class="num">Cores</th>', "")
    body = table[table.index("<tbody>") :]
    assert '<td class="num">' in body
    assert body.count('class="num"') == 2 * 1  # one row, two numeric cells


def test_view_grid_aligns_numeric_and_formula_columns(client, login):
    _seed_numeric(client, login)
    client.post(
        "/views",
        data={
            "name": "V",
            "entity_id": "1",
            "col": ["base:name", "base:cores", "base:price"],
            "calc": [
                json.dumps({"kind": "formula", "label": "Both", "expr": "{cores} * {price}"}),
                json.dumps(
                    {
                        "kind": "concat",
                        "label": "Label",
                        "parts": ["name", "cores"],
                        "separator": "/",
                    }
                ),
            ],
        },
        follow_redirects=False,
    )
    html = client.get("/views/1").text
    table = html[html.index('<table class="table"') :]
    thead = table[: table.index("</thead>")]
    assert '<th class="num">Cores</th>' in thead
    assert '<th class="num">Price</th>' in thead
    # A formula is numeric (right-aligned), a text join is not.
    assert '<th class="num">Both</th>' in thead
    assert "<th>Label</th>" in thead
    assert "<th>Name</th>" in thead


def test_totals_footer_aligns_with_its_column(client, login):
    _seed_numeric(client, login)
    client.post(
        "/views",
        data={
            "name": "V",
            "entity_id": "1",
            "col": ["base:name", "base:cores"],
            "col_total": ["", "sum"],
        },
        follow_redirects=False,
    )
    html = client.get("/views/1").text
    assert '<td class="total-cell num" title="sum">' in html


def test_dashboard_widget_grid_aligns_numeric_columns(client, login):
    _seed_numeric(client, login)
    client.post(
        "/dashboard/widgets",
        data={
            "title": "Servers",
            "widget_type": "table",
            "entity_id": "1",
            "view_id": "",
            "width": "6",
        },
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert '<th class="num">Cores</th>' in html
    assert "<th>Name</th>" in html


def test_numeric_alignment_css_is_served(client, login):
    login()
    assert (
        ".table th.num, .table td.num { text-align: right; }"
        in client.get("/static/style.css").text
    )
