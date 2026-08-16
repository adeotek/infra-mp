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
