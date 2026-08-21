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
# Web UI
# --------------------------------------------------------------------------- #


def test_tokens_page_requires_login(client):
    r = client.get("/settings/api-tokens", follow_redirects=False)
    assert r.status_code == 303


def test_create_token_shows_plaintext_once(client, login):
    login()
    r = client.post("/settings/api-tokens", data={"name": "agent"}, follow_redirects=False)
    assert r.status_code == 200
    assert "token-reveal" in r.text
    assert 'id="new-token-value"' in r.text
    import re

    match = re.search(r"imp_[0-9a-f]{48}", r.text)
    assert match, "plaintext not found in create response"
    plaintext = match.group(0)
    # A subsequent GET must not show the plaintext again (the prefix column
    # legitimately shows a truncated form — only the full token must be gone).
    r2 = client.get("/settings/api-tokens")
    assert "token-reveal" not in r2.text
    assert plaintext not in r2.text


def test_create_token_requires_name(client, login):
    login()
    r = client.post("/settings/api-tokens", data={"name": "  "}, follow_redirects=False)
    assert r.status_code == 400
    assert "Token name is required" in r.text


def test_admin_sees_all_tokens_others_only_own(client, login, db_session):
    _create_user_via_web(client, login, "viewer1", "viewer", "viewer-pass-123")
    _create_user_via_web(client, login, "maint1", "maintainer", "maint-pass-123")
    _mint(db_session, "admin", "admin-token")
    _mint(db_session, "viewer1", "viewer-token")
    _mint(db_session, "maint1", "maint-token")

    login()  # admin
    page = client.get("/settings/api-tokens")
    assert "admin-token" in page.text
    assert "viewer-token" in page.text
    assert "maint-token" in page.text
    assert "<th>User</th>" in page.text

    login("viewer1", "viewer-pass-123")
    page = client.get("/settings/api-tokens")
    assert "viewer-token" in page.text
    assert "admin-token" not in page.text
    assert "maint-token" not in page.text
    assert "<th>User</th>" not in page.text


def test_viewer_can_manage_own_tokens(client, login, db_session):
    _create_user_via_web(client, login, "viewer2", "viewer", "viewer-pass-123")
    _mint(db_session, "viewer2", "mine")
    login("viewer2", "viewer-pass-123")
    token = db_session.query(ApiToken).filter_by(name="mine").one()
    r = client.post(f"/settings/api-tokens/{token.id}/revoke", follow_redirects=False)
    assert r.status_code == 303
    db_session.refresh(token)
    assert token.is_active is False


def test_viewer_cannot_revoke_others_token(client, login, db_session):
    _create_user_via_web(client, login, "viewer3", "viewer", "viewer-pass-123")
    _mint(db_session, "admin", "admins-token")
    token = db_session.query(ApiToken).filter_by(name="admins-token").one()
    login("viewer3", "viewer-pass-123")
    r = client.post(f"/settings/api-tokens/{token.id}/revoke", follow_redirects=False)
    assert r.status_code == 403
    db_session.refresh(token)
    assert token.is_active is True


def test_admin_can_revoke_any_token(client, login, db_session):
    _create_user_via_web(client, login, "viewer4", "viewer", "viewer-pass-123")
    _mint(db_session, "viewer4", "others")
    token = db_session.query(ApiToken).filter_by(name="others").one()
    login()  # admin
    r = client.post(f"/settings/api-tokens/{token.id}/revoke", follow_redirects=False)
    assert r.status_code == 303
    db_session.refresh(token)
    assert token.is_active is False


def test_nav_has_api_tokens_link(client, login):
    login()
    r = client.get("/dashboard")
    assert 'href="/settings/api-tokens"' in r.text
