"""HTTP tests for user management routes (admin-only)."""


def test_users_index(client, login):
    login()
    assert client.get("/users").status_code == 200


def test_new_user_page(client, login):
    login()
    assert client.get("/users/new").status_code == 200


def test_create_user(client, login):
    login()
    resp = client.post(
        "/users",
        data={
            "username": "bob",
            "display_name": "Bob",
            "role": "viewer",
            "password": "password-123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "bob" in client.get("/users").text


def test_create_user_duplicate(client, login):
    login()
    client.post(
        "/users",
        data={"username": "bob", "role": "viewer", "password": "password-123"},
        follow_redirects=False,
    )
    resp = client.post(
        "/users",
        data={"username": "bob", "role": "viewer", "password": "password-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_create_user_invalid_role_defaults_to_viewer(client, login):
    login()
    resp = client.post(
        "/users",
        data={"username": "bob", "role": "superadmin", "password": "password-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_edit_user_page(client, login):
    login()
    client.post(
        "/users",
        data={"username": "bob", "role": "viewer", "password": "password-123"},
        follow_redirects=False,
    )
    assert client.get("/users/2/edit").status_code == 200


def test_edit_user_page_404(client, login):
    login()
    assert client.get("/users/9999/edit").status_code == 404


def test_update_user(client, login):
    login()
    client.post(
        "/users",
        data={"username": "bob", "role": "viewer", "password": "password-123"},
        follow_redirects=False,
    )
    resp = client.post(
        "/users/2/edit",
        data={"display_name": "Robert", "role": "maintainer", "is_active": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Robert" in client.get("/users").text


def test_update_user_404(client, login):
    login()
    resp = client.post(
        "/users/9999/edit", data={"display_name": "x", "role": "viewer"}, follow_redirects=False
    )
    assert resp.status_code == 404


def test_delete_user(client, login):
    login()
    client.post(
        "/users",
        data={"username": "bob", "role": "viewer", "password": "password-123"},
        follow_redirects=False,
    )
    assert client.post("/users/2/delete", follow_redirects=False).status_code == 303
    assert "bob" not in client.get("/users").text


def test_delete_user_404(client, login):
    login()
    assert client.post("/users/9999/delete", follow_redirects=False).status_code == 404
