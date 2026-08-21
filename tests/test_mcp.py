"""MCP endpoint: token auth, capability enforcement, enablement flag."""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from app.main import create_app
from app.models.api_token import ApiToken
from app.models.enums import DataType
from app.models.user import User
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services import api_token_service
from app.services.schema_service import add_attribute, create_entity

INIT_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "pytest", "version": "0"},
}


def _call(client, method, params, token=None, session=None, raw_id=2):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session:
        headers["mcp-session-id"] = session
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": raw_id, "method": method, "params": params},
        headers=headers,
    )


def _session(client, token):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.headers.get("mcp-session-id")


def _tool(client, name, arguments, token, session):
    """Invoke a tool via tools/call and return the JSON-RPC response."""
    return _call(
        client,
        "tools/call",
        {"name": name, "arguments": arguments},
        token=token,
        session=session,
    )


def _result(r):
    """Unwrap the tool payload from the SDK's response shape.

    Lists arrive as ``structuredContent: {"result": [...]}``, dicts as a JSON
    string in ``content[0].text``, errors as ``isError`` + message text.
    """
    body = r.json()
    assert "error" not in body, body
    result = body["result"]
    sc = result.get("structuredContent")
    if sc:
        return sc["result"] if isinstance(sc, dict) and "result" in sc else sc
    content = result.get("content") or []
    if result.get("isError"):
        message = content[0].get("text") if content else "unknown tool error"
        raise AssertionError(f"tool returned isError: {message}")
    if content and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    return result


def _mint(db, username="admin", name="mcp-token") -> tuple[User, str]:
    user = db.query(User).filter_by(username=username).one()
    plaintext, _ = api_token_service.generate_token(db, user, name)
    return user, plaintext


def _create_user_via_web(client, login, username, role, password):
    login()
    client.post(
        "/users",
        data={
            "username": username,
            "display_name": username.title(),
            "role": role,
            "password": password,
        },
        follow_redirects=False,
    )


def _seed_entity(db, name="Server"):
    entity = create_entity(db, EntityCreate(name=name))
    add_attribute(db, entity, AttributeCreate(name="Hostname", data_type=DataType.TEXT))
    return entity


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #


def test_mcp_requires_token(client):
    r = _call(client, "initialize", INIT_PARAMS)
    assert r.status_code == 401
    assert "www-authenticate" in {k.lower() for k in r.headers}


def test_mcp_rejects_invalid_token(client):
    r = _call(client, "initialize", INIT_PARAMS, token="imp_deadbeef")
    assert r.status_code == 401


def test_mcp_rejects_revoked_token(client, db_session):
    _, plaintext = _mint(db_session)
    session = _session(client, plaintext)
    api_token_service.revoke_token(db_session, db_session.query(ApiToken).one())
    r = _call(client, "tools/list", {}, token=plaintext, session=session)
    assert r.status_code == 401


def test_mcp_rejects_inactive_user_token(client, db_session):
    user, plaintext = _mint(db_session)
    session = _session(client, plaintext)
    user.is_active = False
    db_session.commit()
    r = _call(client, "tools/list", {}, token=plaintext, session=session)
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Capability enforcement
# --------------------------------------------------------------------------- #


def test_viewer_read_tools_work(client, login, db_session):
    _seed_entity(db_session)
    _create_user_via_web(client, login, "viewer", "viewer", "viewer-pass-123")
    _, plaintext = _mint(db_session, "viewer")
    session = _session(client, plaintext)
    r = _tool(client, "list_entities", {}, plaintext, session)
    assert r.status_code == 200
    entities = _result(r)
    assert [e["name"] for e in entities] == ["Server"]
    assert entities[0]["attributes"][0]["slug"] == "hostname"


def test_viewer_cannot_write(client, login, db_session):
    entity = _seed_entity(db_session)
    _create_user_via_web(client, login, "viewer2", "viewer", "viewer-pass-123")
    _, plaintext = _mint(db_session, "viewer2")
    session = _session(client, plaintext)
    args = {"entity_id": entity.id, "data": {"hostname": "srv1"}}
    r = _tool(client, "create_record", args, plaintext, session)
    assert r.status_code == 200
    body = r.json()["result"]
    assert body.get("isError") is True
    assert "create_record" in str(body)


def test_viewer_cannot_list_users(client, login, db_session):
    _create_user_via_web(client, login, "viewer3", "viewer", "viewer-pass-123")
    _, plaintext = _mint(db_session, "viewer3")
    session = _session(client, plaintext)
    r = _tool(client, "list_users", {}, plaintext, session)
    assert r.json()["result"].get("isError") is True


def test_maintainer_can_create_record(client, login, db_session):
    entity = _seed_entity(db_session)
    _create_user_via_web(client, login, "maint", "maintainer", "maint-pass-123")
    _, plaintext = _mint(db_session, "maint")
    session = _session(client, plaintext)
    args = {"entity_id": entity.id, "data": {"hostname": "srv1"}}
    r = _tool(client, "create_record", args, plaintext, session)
    assert r.status_code == 200
    created = _result(r)
    assert created["data"]["hostname"] == "srv1"
    assert created["created_by"] is not None


def test_maintainer_cannot_manage_schema(client, login, db_session):
    _create_user_via_web(client, login, "maint2", "maintainer", "maint-pass-123")
    _, plaintext = _mint(db_session, "maint2")
    session = _session(client, plaintext)
    r = _tool(client, "create_entity", {"name": "Nope"}, plaintext, session)
    assert r.json()["result"].get("isError") is True


def test_admin_full_access(client, login, db_session):
    _create_user_via_web(client, login, "viewer4", "viewer", "viewer-pass-123")
    _, plaintext = _mint(db_session, "admin")
    session = _session(client, plaintext)

    r = _tool(client, "list_users", {}, plaintext, session)
    users = _result(r)
    assert {u["username"] for u in users} >= {"admin", "viewer4"}

    r = _tool(client, "create_entity", {"name": "Switch"}, plaintext, session)
    created = _result(r)
    assert created["name"] == "Switch"

    view_args = {"entity_id": created["id"], "name": "All switches"}
    r = _tool(client, "create_view", view_args, plaintext, session)
    view = _result(r)
    assert view["name"] == "All switches"

    r = _tool(client, "list_views", {}, plaintext, session)
    assert any(v["id"] == view["id"] for v in _result(r))


def test_mcp_disabled_flag(settings, engine):
    disabled = settings.model_copy(update={"mcp_enabled": False})
    app = create_app(disabled)
    with TestClient(app) as c:
        r = c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": INIT_PARAMS},
        )
        assert r.status_code == 404


def test_tools_list_registers_all_tools(client, db_session):
    _, plaintext = _mint(db_session)
    session = _session(client, plaintext)
    r = _call(client, "tools/list", {}, token=plaintext, session=session)
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {
        "list_entities",
        "get_entity",
        "list_records",
        "get_record",
        "create_record",
        "update_record",
        "delete_record",
        "create_entity",
        "update_entity",
        "delete_entity",
        "create_attribute",
        "update_attribute",
        "delete_attribute",
        "list_views",
        "get_view",
        "view_records",
        "create_view",
        "update_view",
        "delete_view",
        "dashboard_stats",
        "list_users",
        "list_dashboard_widgets",
    } <= names
