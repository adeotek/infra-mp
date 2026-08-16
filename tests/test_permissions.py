"""Role-based access control tests via HTTP."""


def _create_user(client, login, username, role, password):
    login()
    return client.post(
        "/users",
        data={
            "username": username,
            "display_name": username.title(),
            "role": role,
            "password": password,
        },
        follow_redirects=False,
    )


def _seed_entity(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text", "is_required": "on"},
        follow_redirects=False,
    )


def test_maintainer_can_create_but_not_delete(client, login):
    _seed_entity(client, login)
    _create_user(client, login, "maint", "maintainer", "maint-pass-123")
    login("maint", "maint-pass-123")

    # Read allowed.
    assert client.get("/entities").status_code == 200
    # Create record allowed.
    assert (
        client.post(
            "/entities/1/records", data={"hostname": "web01"}, follow_redirects=False
        ).status_code
        == 303
    )
    # Delete record denied.
    assert client.post("/records/1/delete", follow_redirects=False).status_code == 403


def test_maintainer_cannot_manage_schema_or_users(client, login):
    _seed_entity(client, login)
    _create_user(client, login, "maint", "maintainer", "maint-pass-123")
    login("maint", "maint-pass-123")

    assert client.get("/users").status_code == 403
    assert (
        client.post("/entities", data={"name": "Nope"}, follow_redirects=False).status_code == 403
    )
    assert (
        client.post(
            "/entities/1/attributes",
            data={"name": "X", "data_type": "text"},
            follow_redirects=False,
        ).status_code
        == 403
    )


def test_viewer_is_read_only(client, login):
    _seed_entity(client, login)
    _create_user(client, login, "viewer", "viewer", "viewer-pass-123")
    login("viewer", "viewer-pass-123")

    assert client.get("/entities").status_code == 200
    assert client.get("/entities/1/records").status_code == 200
    assert client.get("/entities/1/records/new", follow_redirects=False).status_code == 403
    assert (
        client.post(
            "/entities/1/records", data={"hostname": "nope"}, follow_redirects=False
        ).status_code
        == 403
    )


def test_admin_can_manage_users(client, login):
    login()
    assert client.get("/users").status_code == 200
    resp = client.post(
        "/users",
        data={
            "username": "newadmin",
            "display_name": "New",
            "role": "admin",
            "password": "password-123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_cannot_delete_own_account(client, login):
    login()
    # admin is user id 1 in a fresh DB
    assert client.post("/users/1/delete", follow_redirects=False).status_code == 303
    # The flash error should be carried; admin still exists (can still log in).
    login()
    assert client.get("/users").status_code == 200
