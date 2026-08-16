"""HTTP tests for saved-view routes (CRUD, validation, and 404s)."""


def _seed_server(client, login):
    login()
    assert (
        client.post("/entities", data={"name": "Server"}, follow_redirects=False).status_code == 303
    )
    assert (
        client.post(
            "/entities/1/attributes",
            data={"name": "Name", "data_type": "text", "is_required": "on"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/1/attributes",
            data={"name": "Cores", "data_type": "integer"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/1/attributes",
            data={"name": "Status", "data_type": "enum", "options": "active\nretired"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    for name, cores in [("alpha", "4"), ("bravo", "8")]:
        assert (
            client.post(
                "/entities/1/records",
                data={"name": name, "cores": cores, "status": "active"},
                follow_redirects=False,
            ).status_code
            == 303
        )


def test_views_index_renders(client, login):
    _seed_server(client, login)
    assert client.get("/views").status_code == 200


def test_new_view_choose_entity(client, login):
    _seed_server(client, login)
    assert client.get("/views/new").status_code == 200


def test_new_view_with_entity(client, login):
    _seed_server(client, login)
    assert client.get("/views/new", params={"entity_id": 1}).status_code == 200


def test_new_view_missing_entity_404(client, login):
    _seed_server(client, login)
    assert client.get("/views/new", params={"entity_id": 9999}).status_code == 404


def test_create_view(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/views",
        data={
            "name": "Active Servers",
            "entity_id": "1",
            "columns": ["name", "cores"],
            "sort_slug": "cores",
            "sort_dir": "desc",
            "filter_slug": ["status"],
            "filter_op": ["eq"],
            "filter_value": ["active"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/views/1" in resp.headers["location"]


def test_create_view_requires_name(client, login):
    _seed_server(client, login)
    resp = client.post("/views", data={"name": "", "entity_id": "1"}, follow_redirects=False)
    assert resp.status_code == 400


def test_create_view_missing_entity_404(client, login):
    _seed_server(client, login)
    resp = client.post("/views", data={"name": "X", "entity_id": "9999"}, follow_redirects=False)
    assert resp.status_code == 404


def test_view_detail(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    assert client.get("/views/1").status_code == 200


def test_view_detail_404(client, login):
    _seed_server(client, login)
    assert client.get("/views/9999").status_code == 404


def test_edit_view_page(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    assert client.get("/views/1/edit").status_code == 200


def test_edit_view_page_404(client, login):
    _seed_server(client, login)
    assert client.get("/views/9999/edit").status_code == 404


def test_update_view(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    resp = client.post(
        "/views/1/edit", data={"name": "Renamed", "entity_id": "1"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "Renamed" in client.get("/views/1").text


def test_update_view_requires_name(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    resp = client.post("/views/1/edit", data={"name": "", "entity_id": "1"}, follow_redirects=False)
    assert resp.status_code == 400


def test_delete_view(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    assert client.post("/views/1/delete", follow_redirects=False).status_code == 303
    assert client.get("/views/1").status_code == 404


def test_delete_view_404(client, login):
    _seed_server(client, login)
    assert client.post("/views/9999/delete", follow_redirects=False).status_code == 404
