"""Authentication tests via HTTP."""


def test_healthz_is_open(client):
    assert client.get("/healthz").status_code == 200


def test_login_page_renders(client):
    assert client.get("/login").status_code == 200


def test_unauthenticated_request_redirects_to_login(client):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


def test_login_with_wrong_password(client):
    resp = client.post(
        "/login", data={"username": "admin", "password": "wrong"}, follow_redirects=False
    )
    assert resp.status_code == 401


def test_login_success(client, login):
    resp = login()
    assert resp.status_code == 303
    assert client.get("/dashboard").status_code == 200


def test_logout_invalidates_session(client, login):
    login()
    assert client.post("/logout", follow_redirects=False).status_code == 303
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 303


def test_admin_is_seeded_on_first_startup(client, login):
    login()
    assert client.get("/users").status_code == 200
