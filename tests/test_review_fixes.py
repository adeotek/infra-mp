"""Tests for the security hardening and bug fixes from the Aug 2026 reviews.

Covers: CSRF middleware, login rate limiting, security headers, trusted
hosts, last-admin guard, password strength, token expiry/delete, backup
limits, widget validation, MCP fixes, and data-coercion fixes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import zipfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.api_token import ApiToken
from app.models.dashboard import DashboardWidget
from app.models.enums import DataType, Role
from app.models.mixins import utcnow
from app.models.user import User
from app.schemas.attribute import AttributeCreate, AttributeUpdate
from app.schemas.entity import EntityCreate
from app.services import api_token_service
from app.services.record_service import create_record
from app.services.schema_service import (
    SchemaError,
    add_attribute,
    create_entity,
    get_entity_with_attributes,
    update_attribute,
)
from app.services.user_service import UserError, update_user
from app.services.validation import coerce_value

INIT_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "pytest", "version": "0"},
}


def _csrf_for(client, settings, cookie_name="infra_mp_session"):
    session = client.cookies.get(cookie_name, "") or ""
    digest = hmac.new(settings.secret_key.encode(), session.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:43]


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #


def test_post_without_csrf_is_rejected(raw_client, login):
    login()
    resp = raw_client.post(
        "/entities",
        data={"name": "Nope"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert "CSRF" in resp.text


def test_post_with_wrong_csrf_is_rejected(raw_client, login):
    login()
    resp = raw_client.post(
        "/entities",
        data={"name": "Nope", "csrf_token": "bogus-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_post_with_valid_form_token_succeeds(raw_client, login, settings):
    login()
    token = _csrf_for(raw_client, settings)
    resp = raw_client.post(
        "/entities",
        data={"name": "Server", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_post_with_header_token_succeeds(raw_client, login, settings):
    login()
    token = _csrf_for(raw_client, settings)
    resp = raw_client.post(
        "/entities",
        data={"name": "Server"},
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_mcp_endpoint_is_csrf_exempt(client):
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp.status_code in (400, 401)  # not 403


def test_forms_render_csrf_field(client, login):
    login()
    html = client.get("/dashboard").text
    assert 'name="csrf_token"' in html


# --------------------------------------------------------------------------- #
# Login rate limiting + timing safety
# --------------------------------------------------------------------------- #


def test_login_is_rate_limited(settings, engine):
    settings.login_max_attempts = 3
    settings.login_cooldown_seconds = 60

    app = create_app(settings)

    with TestClient(app) as c:
        for _ in range(3):
            r = c.post(
                "/login",
                data={"username": "admin", "password": "wrong"},
                follow_redirects=False,
            )
            assert r.status_code == 401
        # Blocked even with the correct password while cooling down.
        r = c.post(
            "/login",
            data={"username": "admin", "password": settings.admin_password},
            follow_redirects=False,
        )
        assert r.status_code == 429


def test_unknown_user_timing_path_returns_generic_error(client):
    resp = client.post(
        "/login",
        data={"username": "definitely-not-a-user", "password": "whatever-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert "Invalid username or password" in resp.text


# --------------------------------------------------------------------------- #
# Headers + trusted hosts
# --------------------------------------------------------------------------- #


def test_security_headers_present(client):
    resp = client.get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]


def test_trusted_host_rejects_unknown_host(settings, engine):
    settings.allowed_hosts = "localhost,infra.example.com"

    app = create_app(settings)

    with TestClient(app) as c:
        resp = c.get("/login", headers={"Host": "evil.example.com"})
        assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Users: last-admin guard + password strength
# --------------------------------------------------------------------------- #


def test_update_last_admin_demote_is_rejected(db_session):
    user = User(username="admin", display_name="Admin", role=Role.ADMIN.value, is_active=True)
    from app.auth.password import hash_password

    user.password_hash = hash_password("password-123")
    db_session.add(user)
    db_session.commit()
    with pytest.raises(UserError, match="last active admin"):
        update_user(db_session, user, "Admin", Role.VIEWER, True)
    with pytest.raises(UserError, match="last active admin"):
        update_user(db_session, user, "Admin", Role.ADMIN, False)


def test_create_user_rejects_short_password(client, login):
    login()
    resp = client.post(
        "/users",
        data={"username": "bob", "display_name": "Bob", "role": "viewer", "password": "short"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "at least 8 characters" in resp.text


# --------------------------------------------------------------------------- #
# API tokens: expiry + delete revoked
# --------------------------------------------------------------------------- #


def test_token_expiry_is_enforced(db_session):
    user = db_session.query(User).filter_by(username="admin").one_or_none()
    if user is None:
        from app.services.user_service import create_user as create

        user = create(db_session, "admin", "Admin", Role.ADMIN, "password-123")
    plaintext, _ = api_token_service.generate_token(
        db_session, user, "expiring", expires_at=utcnow() - timedelta(days=1)
    )
    assert api_token_service.verify_token(db_session, plaintext) is None

    plaintext2, _ = api_token_service.generate_token(
        db_session, user, "fresh", expires_at=utcnow() + timedelta(days=30)
    )
    assert api_token_service.verify_token(db_session, plaintext2) is not None


def test_admin_can_delete_revoked_token(client, login, db_session):
    login()
    plaintext, _ = api_token_service.generate_token(
        db_session, db_session.query(User).filter_by(username="admin").one(), "doomed"
    )
    token = db_session.query(ApiToken).filter_by(name="doomed").one()
    api_token_service.revoke_token(db_session, token)
    resp = client.post(
        f"/settings/api-tokens/{token.id}/delete",
        data={"return_to": "/settings/api-tokens"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.expunge_all()  # the row was deleted by the request's session
    assert db_session.get(ApiToken, token.id) is None
    assert api_token_service.verify_token(db_session, plaintext) is None


def test_active_token_cannot_be_deleted(client, login, db_session):
    from urllib.parse import unquote

    login()
    _, _ = api_token_service.generate_token(
        db_session, db_session.query(User).filter_by(username="admin").one(), "active-one"
    )
    token = db_session.query(ApiToken).filter_by(name="active-one").one()
    resp = client.post(
        f"/settings/api-tokens/{token.id}/delete",
        data={"return_to": "/settings/api-tokens"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "revoke it first" in unquote(resp.headers["location"])
    db_session.expunge_all()
    assert db_session.get(ApiToken, token.id) is not None


def test_viewer_cannot_delete_tokens(client, login, db_session):
    login()
    client.post(
        "/users",
        data={
            "username": "viewerx",
            "display_name": "Viewer X",
            "role": "viewer",
            "password": "viewer-pass-123",
        },
        follow_redirects=False,
    )
    admin_user = db_session.query(User).filter_by(username="admin").one()
    _, _ = api_token_service.generate_token(db_session, admin_user, "admin-tok")
    token = db_session.query(ApiToken).filter_by(name="admin-tok").one()
    api_token_service.revoke_token(db_session, token)
    login("viewerx", "viewer-pass-123")
    resp = client.post(
        f"/settings/api-tokens/{token.id}/delete",
        data={"return_to": "/settings/api-tokens"},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert db_session.get(ApiToken, token.id) is not None


def test_token_create_page_has_expiry_select(client, login):
    login()
    html = client.get("/settings/api-tokens").text
    assert 'name="expires_days"' in html


# --------------------------------------------------------------------------- #
# Backup limits
# --------------------------------------------------------------------------- #


def _zip_with_db(db_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("infra-mp.db", db_bytes)
    return buf.getvalue()


def test_restore_rejects_oversized_upload(settings, engine, tmp_path):
    import os
    from urllib.parse import unquote

    settings.max_backup_upload_bytes = 1024

    app = create_app(settings)

    with TestClient(app) as c:
        c.post(
            "/login",
            data={"username": "admin", "password": settings.admin_password},
            follow_redirects=False,
        )
        token = _csrf_for(c, settings)
        # Truly random bytes so the zip cannot compress the entry under the cap.
        big = _zip_with_db(os.urandom(4096))
        resp = c.post(
            "/settings/backup/restore",
            data={"csrf_token": token},
            files={"file": ("backup.zip", big, "application/zip")},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "larger than" in unquote(resp.headers["location"])


def test_restore_rejects_oversized_db_entry(settings, engine, tmp_path):
    import os
    from urllib.parse import unquote

    settings.max_backup_db_bytes = 64

    app = create_app(settings)

    with TestClient(app) as c:
        c.post(
            "/login",
            data={"username": "admin", "password": settings.admin_password},
            follow_redirects=False,
        )
        token = _csrf_for(c, settings)
        bomb = _zip_with_db(os.urandom(512))
        resp = c.post(
            "/settings/backup/restore",
            data={"csrf_token": token},
            files={"file": ("backup.zip", bomb, "application/zip")},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "too large" in unquote(resp.headers["location"])


# --------------------------------------------------------------------------- #
# Dashboard: widget validation + orphaned view guard
# --------------------------------------------------------------------------- #


def test_widget_type_is_validated(client, login):
    from urllib.parse import unquote

    login()
    resp = client.post(
        "/dashboard/widgets",
        data={
            "title": "Bogus",
            "widget_type": "chart",
            "entity_id": "",
            "view_id": "",
            "width": "1/2",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Unknown widget type" in unquote(resp.headers["location"])


def test_dashboard_survives_orphaned_view_id(client, login, db_session):
    from sqlalchemy import text

    login()
    client.post(
        "/entities",
        data={"name": "Servers"},
        follow_redirects=False,
    )
    # An orphaned view_id normally cannot exist (FK enforcement), so simulate
    # a legacy/manual edit with FKs off — the render must still survive.
    db_session.execute(text("PRAGMA foreign_keys=OFF"))
    widget = DashboardWidget(
        title="Orphan", widget_type="table", entity_id=1, view_id=9999, sort_order=1, width="1/2"
    )
    db_session.add(widget)
    db_session.commit()
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    resp = client.get("/dashboard")
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# MCP fixes
# --------------------------------------------------------------------------- #


def _mcp_session(client, token):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.headers.get("mcp-session-id")


def _mcp_call(client, name, arguments, token, session):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers={"Authorization": f"Bearer {token}", "mcp-session-id": session},
    )


def test_mcp_list_dashboard_widgets_returns_width(client, login, db_session):
    login()
    user = db_session.query(User).filter_by(username="admin").one()
    plaintext, _ = api_token_service.generate_token(db_session, user, "mcp-widgets")
    db_session.add(
        DashboardWidget(title="W1", widget_type="count", entity_id=None, sort_order=1, width="full")
    )
    db_session.commit()
    session = _mcp_session(client, plaintext)
    resp = _mcp_call(client, "list_dashboard_widgets", {}, plaintext, session)
    body = resp.json()
    assert "error" not in body, body
    sc = body["result"].get("structuredContent")
    widgets = sc["result"] if isinstance(sc, dict) and "result" in sc else sc
    assert widgets[0]["width"] == "full"
    assert "span" not in widgets[0]


def test_mcp_list_records_sorts_numbers_numerically(client, login, db_session):
    login()
    user = db_session.query(User).filter_by(username="admin").one()
    plaintext, _ = api_token_service.generate_token(db_session, user, "mcp-sort")
    entity = create_entity(db_session, EntityCreate(name="Sortable"))
    add_attribute(db_session, entity, AttributeCreate(name="Num", data_type=DataType.INTEGER))
    entity = get_entity_with_attributes(db_session, entity.id)
    assert entity is not None
    create_record(db_session, entity, entity.attributes, {"num": "10"})
    create_record(db_session, entity, entity.attributes, {"num": "2"})
    session = _mcp_session(client, plaintext)
    resp = _mcp_call(
        client,
        "list_records",
        {"entity_id": entity.id, "sort": "num"},
        plaintext,
        session,
    )
    body = resp.json()
    assert "error" not in body, body
    result = body["result"]
    payload = result.get("structuredContent") or {}
    if isinstance(payload, dict) and "result" in payload:
        records = payload["result"]["records"]
    else:
        records = json.loads(result["content"][0]["text"])["records"]
    assert [r["data"]["num"] for r in records] == [2, 10]


# --------------------------------------------------------------------------- #
# Data coercion fixes
# --------------------------------------------------------------------------- #


def test_datetime_strips_timezone_to_naive_utc():
    assert coerce_value(DataType.DATETIME, "2024-01-15T10:30:00+02:00") == "2024-01-15T10:30:00"


def test_unique_many_reference_never_collides(db_session):
    a = create_entity(db_session, EntityCreate(name="Alpha"))
    add_attribute(db_session, a, AttributeCreate(name="Name", data_type=DataType.TEXT))
    b = create_entity(db_session, EntityCreate(name="Beta"))
    add_attribute(
        db_session,
        b,
        AttributeCreate(
            name="Alphas",
            data_type=DataType.REFERENCE,
            reference_entity_id=a.id,
            cardinality="many",
            is_unique=True,
        ),
    )
    a = get_entity_with_attributes(db_session, a.id)
    b = get_entity_with_attributes(db_session, b.id)
    a1 = create_record(db_session, a, a.attributes, {"name": "A1"})
    # Two records with the SAME many-reference list must not trip uniqueness.
    create_record(db_session, b, b.attributes, {"alphas": [a1.id]})
    r2 = create_record(db_session, b, b.attributes, {"alphas": [a1.id]})
    assert r2.id is not None


def test_update_attribute_rejects_structural_change_with_records(db_session):
    entity = create_entity(db_session, EntityCreate(name="Machines"))
    attr = add_attribute(
        db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER)
    )
    entity = get_entity_with_attributes(db_session, entity.id)
    create_record(db_session, entity, entity.attributes, {"cores": "8"})
    with pytest.raises(SchemaError, match="data type"):
        update_attribute(
            db_session,
            attr,
            AttributeUpdate(name="Cores", data_type=DataType.TEXT, is_unique=False, is_key=False),
        )


def test_flash_type_param_is_whitelisted(client, login):
    login()
    resp = client.get("/dashboard?flash=hello&flash_type=evil")
    assert "flash-evil" not in resp.text
    assert "flash-success" in resp.text


def test_cookie_secure_when_base_url_is_https(settings, engine, tmp_path):
    settings.base_url = "https://infra.example.com"

    app = create_app(settings)

    with TestClient(app) as c:
        r = c.post(
            "/login",
            data={"username": "admin", "password": settings.admin_password},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "Secure" in r.headers["set-cookie"]


def test_dummy_verify_constant_exists():
    from app.routes.auth import _DUMMY_HASH

    assert _DUMMY_HASH
