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
