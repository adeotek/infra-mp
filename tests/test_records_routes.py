"""HTTP tests for record CRUD routes (validation and 404s)."""


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


def test_records_index(client, login):
    _seed_server(client, login)
    assert client.get("/entities/1/records").status_code == 200


def test_records_index_404(client, login):
    _seed_server(client, login)
    assert client.get("/entities/9999/records").status_code == 404


def test_new_record_page(client, login):
    _seed_server(client, login)
    assert client.get("/entities/1/records/new").status_code == 200


def test_create_record_success(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/entities/1/records", data={"name": "web01", "cores": "8"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "web01" in client.get("/entities/1/records").text


def test_create_record_missing_required(client, login):
    _seed_server(client, login)
    resp = client.post("/entities/1/records", data={"cores": "8"}, follow_redirects=False)
    assert resp.status_code == 400


def test_create_record_invalid_value(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/entities/1/records", data={"name": "web01", "cores": "abc"}, follow_redirects=False
    )
    assert resp.status_code == 400


def test_edit_record_page(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    assert client.get("/records/1/edit").status_code == 200


def test_edit_record_page_404(client, login):
    _seed_server(client, login)
    assert client.get("/records/9999/edit").status_code == 404


def test_update_record_success(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01", "cores": "8"}, follow_redirects=False)
    resp = client.post(
        "/records/1/edit", data={"name": "web01", "cores": "16"}, follow_redirects=False
    )
    assert resp.status_code == 303


def test_update_record_missing_required(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    resp = client.post("/records/1/edit", data={"cores": "8"}, follow_redirects=False)
    assert resp.status_code == 400


def test_update_record_404(client, login):
    _seed_server(client, login)
    resp = client.post("/records/9999/edit", data={"name": "x"}, follow_redirects=False)
    assert resp.status_code == 404


def test_delete_record(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    assert client.post("/records/1/delete", follow_redirects=False).status_code == 303
    # Soft-deleted: no longer listed.
    assert "web01" not in client.get("/entities/1/records").text


def test_delete_record_404(client, login):
    _seed_server(client, login)
    assert client.post("/records/9999/delete", follow_redirects=False).status_code == 404


def test_record_form_renders_attribute_hint(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text", "hint": "FQDN of the server."},
        follow_redirects=False,
    )
    html = client.get("/entities/1/records/new").text
    assert "FQDN of the server." in html
    assert 'class="hint"' in html


def test_record_list_shows_system_columns(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    html = client.get("/entities/1/records").text
    assert "Created at" in html
    assert "Created by" in html
    assert "Last modified at" in html
    assert "Last modified by" in html


def test_record_edit_form_shows_metadata(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    html = client.get("/records/1/edit").text
    assert "Record metadata" in html
    assert "admin" in html  # created_by resolves to the admin username


def test_inactive_attribute_hidden_from_record_form(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post(
        "/entities/1/attributes",
        data={"name": "Cores", "data_type": "integer"},
        follow_redirects=False,
    )
    client.post(
        "/attributes/2/edit",
        data={"name": "Cores", "data_type": "integer", "is_active": "false"},
        follow_redirects=False,
    )
    html = client.get("/entities/1/records/new").text
    assert "Name" in html
    assert "Cores" not in html
