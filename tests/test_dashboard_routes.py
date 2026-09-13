"""HTTP tests for the dashboard and widget routes."""


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
            "width": "full",
        },
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert "widget-span-4" in html
    assert "<td>Full</td>" in client.get("/dashboard/config").text


def test_create_widget_defaults_to_half_width(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert "widget-span-2" in html
    assert "widget-span-4" not in html


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
    assert "widget-span-2" in client.get("/dashboard").text


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
            "width": "3/4",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "widget-span-3" in client.get("/dashboard").text


def test_widget_title_links_to_entity_records(client, login):
    _seed_server(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "Servers", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert 'href="/entities/1/records" class="widget-title-link">Servers</a>' in html


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


def test_table_widget_without_copy_flag_has_no_copy_button(client, login):
    _seed_server(client, login)
    _add_table_widget(client)
    html = client.get("/dashboard").text
    assert "web01" in html
    assert "copy-btn" not in html
