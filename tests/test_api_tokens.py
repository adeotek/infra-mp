"""API token service and management UI."""

from __future__ import annotations

from app.models.api_token import ApiToken
from app.models.enums import Role
from app.models.user import User
from app.services import api_token_service, user_service


def _user(db, username: str = "admin") -> User:
    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = user_service.create_user(db, username, username.title(), Role.ADMIN, "password-123")
    return user


def _mint(db, username: str = "admin", name: str = "test-token") -> tuple[User, str]:
    user = _user(db, username)
    plaintext, _ = api_token_service.generate_token(db, user, name)
    return user, plaintext


def _create_user_via_web(client, login, username, role, password):
    login()
    r = client.post(
        "/users",
        data={
            "username": username,
            "display_name": username.title(),
            "role": role,
            "password": password,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


def test_generate_and_verify_token(db_session):
    user, plaintext = _mint(db_session)
    assert plaintext.startswith("imp_")
    assert len(plaintext) == 4 + 48
    stored = db_session.query(ApiToken).one()
    assert stored.token_hash != plaintext
    assert stored.is_active is True
    assert plaintext.startswith(stored.token_prefix)
    assert api_token_service.verify_token(db_session, plaintext).id == user.id


def test_verify_rejects_wrong_token(db_session):
    _mint(db_session)
    assert api_token_service.verify_token(db_session, "imp_deadbeef") is None
    assert api_token_service.verify_token(db_session, "") is None
    assert api_token_service.verify_token(db_session, "not-a-token") is None


def test_verify_rejects_revoked_token(db_session):
    _, plaintext = _mint(db_session)
    api_token_service.revoke_token(db_session, db_session.query(ApiToken).one())
    assert api_token_service.verify_token(db_session, plaintext) is None


def test_verify_rejects_inactive_user(db_session):
    user, plaintext = _mint(db_session)
    user.is_active = False
    db_session.commit()
    assert api_token_service.verify_token(db_session, plaintext) is None


def test_verify_updates_last_used(db_session):
    _, plaintext = _mint(db_session)
    token = db_session.query(ApiToken).one()
    assert token.last_used_at is None
    api_token_service.verify_token(db_session, plaintext)
    db_session.refresh(token)
    assert token.last_used_at is not None


def test_revoke_removes_access(db_session):
    _, plaintext = _mint(db_session)
    token = db_session.query(ApiToken).one()
    api_token_service.revoke_token(db_session, token)
    db_session.refresh(token)
    assert token.is_active is False
    assert api_token_service.verify_token(db_session, plaintext) is None


# --------------------------------------------------------------------------- #
# Web UI — admin page (all users)
# --------------------------------------------------------------------------- #


def test_admin_tokens_page_requires_login(client):
    r = client.get("/settings/api-tokens", follow_redirects=False)
    assert r.status_code == 303


def test_admin_tokens_page_forbidden_for_viewer(client, login):
    _create_user_via_web(client, login, "viewer1", "viewer", "viewer-pass-123")
    login("viewer1", "viewer-pass-123")
    r = client.get("/settings/api-tokens", follow_redirects=False)
    assert r.status_code == 403


def test_admin_page_shows_all_tokens_with_filter(client, login, db_session):
    _create_user_via_web(client, login, "viewer2", "viewer", "viewer-pass-123")
    _create_user_via_web(client, login, "maint1", "maintainer", "maint-pass-123")
    _mint(db_session, "admin", "admin-token")
    _mint(db_session, "viewer2", "viewer-token")
    _mint(db_session, "maint1", "maint-token")

    login()  # admin
    page = client.get("/settings/api-tokens")
    assert "admin-token" in page.text
    assert "viewer-token" in page.text
    assert "maint-token" in page.text
    assert "<th>User</th>" in page.text
    assert 'id="token-user-filter"' in page.text
    assert "data-user-id=" in page.text
    # one option per user plus "All users"
    for username in ("admin", "viewer2", "maint1"):
        assert f">{username}</option>" in page.text


def test_admin_revokes_any_token(client, login, db_session):
    _create_user_via_web(client, login, "viewer3", "viewer", "viewer-pass-123")
    _mint(db_session, "viewer3", "others")
    token = db_session.query(ApiToken).filter_by(name="others").one()
    login()  # admin
    r = client.post(
        f"/settings/api-tokens/{token.id}/revoke",
        data={"return_to": "/settings/api-tokens"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/settings/api-tokens?flash=")
    db_session.refresh(token)
    assert token.is_active is False


# --------------------------------------------------------------------------- #
# Web UI — personal page (own tokens)
# --------------------------------------------------------------------------- #


def test_my_tokens_page_requires_login(client):
    r = client.get("/settings/my-tokens", follow_redirects=False)
    assert r.status_code == 303


def test_create_token_shows_plaintext_once(client, login):
    login()
    r = client.post("/settings/my-tokens", data={"name": "agent"}, follow_redirects=False)
    assert r.status_code == 200
    assert "token-reveal" in r.text
    assert 'id="new-token-value"' in r.text
    import re

    match = re.search(r"imp_[0-9a-f]{48}", r.text)
    assert match, "plaintext not found in create response"
    plaintext = match.group(0)
    # A subsequent GET must not show the plaintext again (the prefix column
    # legitimately shows a truncated form — only the full token must be gone).
    r2 = client.get("/settings/my-tokens")
    assert "token-reveal" not in r2.text
    assert plaintext not in r2.text


def test_create_token_requires_name(client, login):
    login()
    r = client.post("/settings/my-tokens", data={"name": "  "}, follow_redirects=False)
    assert r.status_code == 400
    assert "Token name is required" in r.text


def test_my_tokens_page_shows_only_own(client, login, db_session):
    _create_user_via_web(client, login, "viewer4", "viewer", "viewer-pass-123")
    _mint(db_session, "admin", "admin-token")
    _mint(db_session, "viewer4", "viewer-token")

    login("viewer4", "viewer-pass-123")
    page = client.get("/settings/my-tokens")
    assert "viewer-token" in page.text
    assert "admin-token" not in page.text
    assert "<th>User</th>" not in page.text
    assert 'id="token-user-filter"' not in page.text


def test_user_can_revoke_own_token(client, login, db_session):
    _create_user_via_web(client, login, "viewer5", "viewer", "viewer-pass-123")
    _mint(db_session, "viewer5", "mine")
    token = db_session.query(ApiToken).filter_by(name="mine").one()
    login("viewer5", "viewer-pass-123")
    r = client.post(
        f"/settings/api-tokens/{token.id}/revoke",
        data={"return_to": "/settings/my-tokens"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/settings/my-tokens?flash=")
    db_session.refresh(token)
    assert token.is_active is False


def test_viewer_cannot_revoke_others_token(client, login, db_session):
    _create_user_via_web(client, login, "viewer6", "viewer", "viewer-pass-123")
    _mint(db_session, "admin", "admins-token")
    token = db_session.query(ApiToken).filter_by(name="admins-token").one()
    login("viewer6", "viewer-pass-123")
    r = client.post(
        f"/settings/api-tokens/{token.id}/revoke",
        data={"return_to": "/settings/my-tokens"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    db_session.refresh(token)
    assert token.is_active is True


def test_revoke_rejects_unknown_return_to(client, login, db_session):
    _mint(db_session, "admin", "mine-token")
    token = db_session.query(ApiToken).filter_by(name="mine-token").one()
    login()  # admin
    r = client.post(
        f"/settings/api-tokens/{token.id}/revoke",
        data={"return_to": "https://evil.example"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/settings/api-tokens?flash=")


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #


def test_nav_links(client, login):
    # Admin: sidebar link + header user-menu link.
    login()
    r = client.get("/dashboard")
    assert 'href="/settings/api-tokens"' in r.text
    assert 'href="/settings/my-tokens"' in r.text

    # Viewer: header user-menu link only.
    _create_user_via_web(client, login, "viewer7", "viewer", "viewer-pass-123")
    login("viewer7", "viewer-pass-123")
    r = client.get("/dashboard")
    assert 'href="/settings/api-tokens"' not in r.text
    assert 'href="/settings/my-tokens"' in r.text
