"""Regression tests for the September 2026 review hardening pass.

Covers: CSRF body-budget cap, exact-path /login exemption, login origin
check, session invalidation on password change/reset, user deletion with
schema ownership (FK SET NULL), CSV export/import round-trip of
formula-looking values, the render-time safe_url filter, MCP tool error
sanitisation, and Cache-Control on authenticated pages.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models.enums import DataType, Role
from app.models.user import User
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services import record_service, view_service
from app.services.csv_service import (
    _unmark_formula_cell,
    export_records_csv,
    import_record_rows,
    parse_csv_upload,
)
from app.services.schema_service import add_attribute, create_entity
from app.services.user_service import create_user, delete_user


def _prepare_db(settings: Settings) -> None:
    """Create the schema in the settings' database (tests skip Alembic)."""
    from app.db import Base, build_engine

    engine = build_engine(settings.database_url, settings.data_dir)
    Base.metadata.create_all(engine)
    engine.dispose()


def _raw_client(settings: Settings):
    """A plain TestClient (no CSRF auto-signing) for rejection paths."""
    from starlette.testclient import TestClient

    _prepare_db(settings)
    return TestClient(create_app(settings))


def _csrf_client(settings: Settings):

    from tests.conftest import _CsrfClient

    _prepare_db(settings)
    return _CsrfClient(create_app(settings), settings)


def _login(client, password, username: str = "admin"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def _session_token(client, settings) -> str:
    session = client.cookies.get(settings.session_cookie_name, "") or ""
    digest = hmac.new(
        settings.secret_key.encode("utf-8"),
        session.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:43]


# --------------------------------------------------------------------------- #
# CSRF middleware hardening
# --------------------------------------------------------------------------- #


def test_csrf_oversized_body_rejected_before_routing(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        secret_key="test-secret-key",
        admin_password="admin-password-123",
        max_backup_upload_bytes=1024,
    )
    with _raw_client(settings) as client:
        # Budget = max_backup_upload_bytes + 64KB slack; a body beyond it must
        # be rejected with 413 by the middleware, never buffered into memory.
        response = client.post("/entities", content=b"x" * (1024 + 64 * 1024 + 1))
        assert response.status_code == 413
        assert "too large" in response.json()["detail"]


def test_csrf_exemption_is_exact_login_path_not_prefix(settings):
    # POST /login2 must NOT inherit /login's exemption: without a token it is
    # rejected by the middleware (403) instead of passing through.
    with _raw_client(settings) as client:
        response = client.post("/login2", data={"username": "admin", "password": "x"})
        assert response.status_code == 403


def test_csrf_form_field_token_still_accepted_under_budget(settings):
    with _csrf_client(settings) as client:
        # A form submission carrying the token in the body passes.
        response = client.post(
            "/entities",
            data={"name": "Budget Entity", "description": "", "icon": ""},
        )
        assert response.status_code in (200, 303)


# --------------------------------------------------------------------------- #
# Login origin check (login-CSRF mitigation)
# --------------------------------------------------------------------------- #


def test_login_rejects_cross_origin(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        secret_key="test-secret-key",
        admin_password="admin-password-123",
    )
    with _raw_client(settings) as client:
        response = client.post(
            "/login",
            data={"username": "admin", "password": "admin-password-123"},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403


def test_login_accepts_same_origin_and_missing_origin(settings):
    with _raw_client(settings) as client:
        origin = f"http://{client.base_url.host}:{client.base_url.port}"
        response = client.post(
            "/login",
            data={"username": "admin", "password": "admin-password-123"},
            headers={"Origin": origin},
            follow_redirects=False,
        )
        assert response.status_code == 303
        # No Origin/Referer (plain clients, tests): allowed through.
        client.cookies.clear()
        response = client.post(
            "/login",
            data={"username": "admin", "password": "admin-password-123"},
            follow_redirects=False,
        )
        assert response.status_code == 303


# --------------------------------------------------------------------------- #
# Session invalidation on password changes
# --------------------------------------------------------------------------- #


def test_self_password_change_keeps_current_session_but_kills_others(settings):
    with _csrf_client(settings) as client:
        _login(client, "admin-password-123")
        first_session = _session_token(client, settings)
        # A second login for the same user creates a second session.
        client.cookies.clear()
        _login(client, "admin-password-123")
        second_session = _session_token(client, settings)
        assert first_session != second_session

        client.cookies.clear()
        _login(client, "admin-password-123")
        response = client.post(
            "/settings/password",
            data={
                "current_password": "admin-password-123",
                "new_password": "new-password-456",
                "confirm_password": "new-password-456",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        # The other two sessions are now dead; the current session survives.
        for session in (first_session, second_session):
            client.cookies.clear()
            client.cookies.set(settings.session_cookie_name, session)
            assert client.get("/dashboard", follow_redirects=False).status_code == 303
        client.cookies.clear()
        _login(client, "new-password-456")
        assert client.get("/dashboard").status_code == 200


def test_admin_reset_invalidates_target_users_sessions(settings, db_session):
    with _csrf_client(settings) as client:
        _login(client, "admin-password-123")
        response = client.post(
            "/users",
            data={
                "username": "alice",
                "display_name": "Alice",
                "role": "viewer",
                "password": "alice-password-1",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        client.cookies.clear()
        _login(client, "alice-password-1", username="alice")
        alice_session = _session_token(client, settings)

        # Admin resets Alice's password.
        client.cookies.clear()
        _login(client, "admin-password-123")
        alice = db_session.execute(select(User).where(User.username == "alice")).scalars().first()
        response = client.post(
            f"/users/{alice.id}/edit",
            data={
                "display_name": "Alice",
                "role": "viewer",
                "password": "alice-password-2",
                "is_active": "on",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

        # Alice's old session is invalid; the new password works.
        client.cookies.clear()
        client.cookies.set(settings.session_cookie_name, alice_session)
        assert client.get("/dashboard", follow_redirects=False).status_code == 303
        client.cookies.clear()
        _login(client, "alice-password-2", username="alice")
        assert client.get("/dashboard").status_code == 200


# --------------------------------------------------------------------------- #
# Deleting a user who owns schema rows (FK ON DELETE SET NULL)
# --------------------------------------------------------------------------- #


def test_delete_user_sets_created_by_null_on_entities_and_views(settings, db_session):
    boss = create_user(db_session, "boss", "Boss", Role.ADMIN, "boss-pass-123")
    owner = create_user(db_session, "schema-owner", "Owner", Role.ADMIN, "owner-pass-123")
    entity = create_entity(db_session, EntityCreate(name="Owned Entity"), created_by=owner.id)
    view = view_service.create_view(db_session, entity, "Owned View", {}, user_id=owner.id)
    db_session.expire_all()

    delete_user(db_session, owner, boss)

    assert db_session.get(User, owner.id) is None
    assert db_session.get(type(entity), entity.id).created_by is None
    assert db_session.get(type(view), view.id).created_by is None


# --------------------------------------------------------------------------- #
# CSV export -> import round trip of formula-looking values
# --------------------------------------------------------------------------- #


def test_csv_round_trip_formula_marker_is_stripped_on_import(db_session):
    entity = create_entity(db_session, EntityCreate(name="Formula"))
    add_attribute(db_session, entity, AttributeCreate(name="Value", data_type=DataType.TEXT))
    record = record_service.create_record(
        db_session, entity, entity.attributes, {"value": "=SUM(A1)"}
    )
    csv_text = export_records_csv(
        entity, [record], record_service.resolve_reference_titles(db_session, entity)
    )
    rows = parse_csv_upload(csv_text.encode("utf-8"))
    assert rows[1][0] == "'=SUM(A1)"  # the export marker is present in the file

    # No key attribute -> import always creates (upsert needs a key).
    created, updated, errors = import_record_rows(db_session, entity, rows)
    assert not errors
    assert created == 1 and updated == 0
    imported = record_service.list_records(db_session, entity.id)[0].data["value"]
    assert imported == "=SUM(A1)"  # stored WITHOUT the marker — lossless round trip


def test_unmark_formula_cell_only_strips_marker_shape():
    assert _unmark_formula_cell("'=SUM(A1)") == "=SUM(A1)"
    assert _unmark_formula_cell("'+42") == "+42"
    assert _unmark_formula_cell("'-not-a-number") == "-not-a-number"
    assert _unmark_formula_cell("'-42") == "'-42"  # numeric minus is DATA
    assert _unmark_formula_cell("'literal apostrophe") == "'literal apostrophe"
    assert _unmark_formula_cell("=plain") == "=plain"  # no marker: untouched


# --------------------------------------------------------------------------- #
# Render-time safe_url filter (defense in depth for link cells)
# --------------------------------------------------------------------------- #


def test_safe_url_filter_allows_http_only():
    from app.templates import templates

    safe_url = templates.env.filters["safe_url"]
    assert safe_url("https://example.com/app") == "https://example.com/app"
    assert safe_url("http://192.168.1.5:8000") == "http://192.168.1.5:8000"
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("data:text/html;base64,PHNjcmlwdD4=") is None
    assert safe_url(None) is None
    assert safe_url("") is None


def test_grid_cell_renders_non_http_link_as_plain_text():
    from app.templates import templates

    raw = templates.env.from_string(
        "{% from '_macros.html' import grid_cell %}{{ grid_cell('x', href) }}"
    )
    out = raw.render(href="https://ok.example")
    assert 'href="https://ok.example"' in out
    out = raw.render(href="javascript:alert(1)")
    assert "javascript:" not in out
    assert "<a" not in out


# --------------------------------------------------------------------------- #
# MCP tool error sanitisation
# --------------------------------------------------------------------------- #


def test_mcp_create_entity_overlong_name_returns_sanitized_error(settings, db_session):
    from tests.test_mcp import _call, _mint, _session

    with _raw_client(settings) as client:
        _user, token = _mint(db_session, username="admin", name="long-name-token")
        session = _session(client, token)
        response = _call(
            client,
            "tools/call",
            {"name": "create_entity", "arguments": {"name": "n" * 300}},
            token=token,
            session=session,
        )
        assert response.status_code == 200
        result = response.json()["result"]
        assert result.get("isError") is True
        message = (result.get("content") or [{}])[0].get("text", "")
        # The message must not leak raw exception internals or SQL.
        assert "ValidationError" not in message
        assert "sqlite" not in message.lower()


# --------------------------------------------------------------------------- #
# Cache-Control on authenticated pages
# --------------------------------------------------------------------------- #


def test_authenticated_html_is_no_store(settings):
    with _csrf_client(settings) as client:
        _login(client, "admin-password-123")
        response = client.get("/dashboard")
        assert response.headers.get("cache-control") == "no-store"


def test_static_assets_keep_their_own_caching(settings):
    with _raw_client(settings) as client:
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert response.headers.get("cache-control") is None
