"""Tests for HTMX modal (fragment) rendering."""

HX = {"HX-Request": "true"}


def _seed_entity(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )


def test_htmx_get_entity_form_returns_fragment(client, login):
    _seed_entity(client, login)
    resp = client.get("/entities/new", headers=HX)
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "sidebar" not in resp.text
    assert "New entity" in resp.text


def test_htmx_get_attribute_form_returns_fragment(client, login):
    _seed_entity(client, login)
    resp = client.get("/entities/1/attributes/new", headers=HX)
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "data_type" in resp.text


def test_htmx_get_change_password_fragment(client, login):
    login()
    resp = client.get("/settings/password", headers=HX)
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "Current password" in resp.text


def test_htmx_get_user_form_fragment(client, login):
    login()
    resp = client.get("/users/new", headers=HX)
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert "New user" in resp.text


def test_htmx_create_entity_success_returns_hx_redirect(client, login):
    login()
    resp = client.post("/entities", data={"name": "Server"}, headers=HX, follow_redirects=False)
    assert resp.status_code == 200
    assert resp.headers.get("HX-Redirect", "").startswith("/entities/1")


def test_htmx_create_entity_error_returns_fragment(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.post("/entities", data={"name": "Server"}, headers=HX, follow_redirects=False)
    assert resp.status_code == 400
    assert "<html" not in resp.text
    assert "already exists" in resp.text


def test_htmx_create_attribute_success_returns_hx_redirect(client, login):
    _seed_entity(client, login)
    resp = client.post(
        "/entities/1/attributes",
        data={"name": "Cores", "data_type": "integer"},
        headers=HX,
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert resp.headers.get("HX-Redirect", "").startswith("/entities/1")


def test_htmx_create_user_success_returns_hx_redirect(client, login):
    login()
    resp = client.post(
        "/users",
        data={"username": "bob", "role": "viewer", "password": "password-123"},
        headers=HX,
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert resp.headers.get("HX-Redirect", "").startswith("/users")


def test_htmx_change_password_success_returns_hx_redirect(client, login, admin_password):
    login()
    resp = client.post(
        "/settings/password",
        data={
            "current_password": admin_password,
            "new_password": "new-pass-123",
            "confirm_password": "new-pass-123",
        },
        headers=HX,
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert resp.headers.get("HX-Redirect", "").startswith("/dashboard")


def test_htmx_change_password_error_returns_fragment(client, login):
    login()
    resp = client.post(
        "/settings/password",
        data={
            "current_password": "wrong",
            "new_password": "new-pass-123",
            "confirm_password": "new-pass-123",
        },
        headers=HX,
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "<html" not in resp.text
    assert "incorrect" in resp.text


def test_non_htmx_still_renders_full_page(client, login):
    _seed_entity(client, login)
    resp = client.get("/entities/new")
    assert resp.status_code == 200
    assert "<html" in resp.text
    assert "sidebar" in resp.text
