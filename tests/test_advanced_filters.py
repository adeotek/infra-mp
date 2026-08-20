"""Advanced filters: engine semantics, endpoints, and page markup.

Advanced filters live on the view config as ``advanced_filter`` (checkbox),
``filter_op`` (global and/or), and ``filters`` rows of
``{"col": "quick" | slug | rel-spec, "op", "value"}``. Each mutation applies
immediately (the view body is re-rendered).
"""

import pytest

from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import create_record, list_records
from app.services.schema_service import (
    add_attribute,
    create_entity,
    get_entity_with_attributes,
    list_entities,
)
from app.services.view_service import apply_config, get_view


@pytest.fixture
def servers(db_session):
    entity = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, entity, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(db_session, entity, AttributeCreate(name="Cores", data_type=DataType.INTEGER))
    add_attribute(
        db_session,
        entity,
        AttributeCreate(name="Status", data_type=DataType.ENUM, options=["active", "retired"]),
    )
    add_attribute(db_session, entity, AttributeCreate(name="Virtual", data_type=DataType.BOOLEAN))
    entity = get_entity_with_attributes(db_session, entity.id)
    for name, cores, status, virtual in [
        ("alpha", 4, "active", True),
        ("bravo", 16, "retired", False),
        ("charlie", None, "active", True),
    ]:
        data = {"name": name, "status": status, "virtual": virtual}
        if cores is not None:
            data["cores"] = cores
        create_record(db_session, entity, entity.attributes, data)
    return entity


def _names(db_session, entity, config):
    records, _ = apply_config(
        entity,
        list_records(db_session, entity.id),
        config,
        list_entities(db_session),
        db=db_session,
    )
    return {r.data["name"] for r in records}


# --------------------------------------------------------------------------- #
# Engine semantics
# --------------------------------------------------------------------------- #


def test_quick_filter_matches_any_cell(db_session, servers):
    config = {"filters": [{"col": "quick", "op": "contains", "value": "16"}]}
    assert _names(db_session, servers, config) == {"bravo"}
    config = {"filters": [{"col": "quick", "op": "contains", "value": "acti"}]}
    assert _names(db_session, servers, config) == {"alpha", "charlie"}


def test_not_contains_op(db_session, servers):
    config = {"filters": [{"col": "status", "op": "not_contains", "value": "act"}]}
    assert _names(db_session, servers, config) == {"bravo"}


def test_global_or_operator(db_session, servers):
    filters = [
        {"col": "name", "op": "eq", "value": "alpha"},
        {"col": "name", "op": "eq", "value": "bravo"},
    ]
    assert _names(db_session, servers, {"filters": filters, "filter_op": "or"}) == {
        "alpha",
        "bravo",
    }
    assert _names(db_session, servers, {"filters": filters, "filter_op": "and"}) == set()


def test_boolean_filter(db_session, servers):
    config = {"filters": [{"col": "virtual", "op": "eq", "value": "true"}]}
    assert _names(db_session, servers, config) == {"alpha", "charlie"}


def test_numeric_gt_filter(db_session, servers):
    config = {"filters": [{"col": "cores", "op": "gt", "value": "8"}]}
    assert _names(db_session, servers, config) == {"bravo"}


def test_legacy_slug_filter_rows_still_work(db_session, servers):
    config = {"filters": [{"slug": "status", "op": "neq", "value": "active"}]}
    assert _names(db_session, servers, config) == {"bravo"}


def test_related_column_filter_by_title(db_session, ref_graph):
    server = ref_graph["server"]
    rack = ref_graph["rack"]
    spec = {
        "path": [{"dir": "up", "ref": "rack", "to": rack.id, "many": "first"}],
        "attr": "name",
    }
    config = {"filters": [{"col": spec, "op": "eq", "value": "R1"}]}
    assert _names(db_session, server, config) == {"A"}


def test_many_reference_filter_matches_any_value(db_session, ref_graph):
    server = ref_graph["server"]
    nic = ref_graph["nic"]
    spec = {
        "path": [{"dir": "up", "ref": "nics", "to": nic.id, "many": "all"}],
        "attr": "ip",
    }
    config = {"filters": [{"col": spec, "op": "contains", "value": "10.0.0.1"}]}
    # A has [10.0.0.1, 10.0.0.2]; D has [10.0.0.1, 10.0.0.2] too.
    assert _names(db_session, server, config) == {"A", "D"}


def test_related_column_numeric_comparison(db_session, ref_graph):
    server = ref_graph["server"]
    nic = ref_graph["nic"]
    spec = {
        "path": [{"dir": "up", "ref": "nics", "to": nic.id, "many": "all"}],
        "attr": "ip",
    }
    config = {"filters": [{"col": spec, "op": "eq", "value": "10.0.0.3"}]}
    assert _names(db_session, server, config) == {"B"}


# --------------------------------------------------------------------------- #
# HTTP: checkbox, bar markup, and filter mutations
# --------------------------------------------------------------------------- #


def _seed(client, login):
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
        "/entities/1/attributes",
        data={"name": "Status", "data_type": "enum", "options": "active\nretired"},
        follow_redirects=False,
    )
    for name, cores, status in [("alpha", "4", "active"), ("bravo", "8", "retired")]:
        client.post(
            "/entities/1/records",
            data={"name": name, "cores": cores, "status": status},
            follow_redirects=False,
        )


def _advanced_view(client):
    client.post(
        "/views",
        data={"name": "V", "entity_id": "1", "advanced_filter": "on"},
        follow_redirects=False,
    )


def test_create_view_with_advanced_checkbox(db_session, client, login):
    _seed(client, login)
    _advanced_view(client)
    view = get_view(db_session, 1)
    assert view.config.get("advanced_filter") is True


def test_detail_renders_bar_when_advanced(client, login):
    _seed(client, login)
    _advanced_view(client)
    html = client.get("/views/1").text
    assert 'id="af-col"' in html
    assert "Quick filter" in html
    assert "view-detail-body" in html
    # No active filters yet: no operator select, Clear disabled.
    assert 'name="filter_op"' not in html
    assert 'value="clear" class="btn"\n            disabled' in html


def test_detail_without_advanced_has_no_bar(client, login):
    _seed(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    html = client.get("/views/1").text
    assert 'id="af-col"' not in html
    assert "Quick filter" not in html


def test_add_quick_filter(client, login):
    _seed(client, login)
    _advanced_view(client)
    resp = client.post(
        "/views/1/filters",
        data={"action": "add", "col": "quick", "value": "bravo"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "alpha" not in resp.text
    assert "bravo" in resp.text
    assert "Quick filter" in resp.text  # active box row
    assert 'name="filter_op"' in resp.text  # operator select appears


def test_add_typed_filter(client, login):
    _seed(client, login)
    _advanced_view(client)
    resp = client.post(
        "/views/1/filters",
        data={"action": "add", "col": "base:cores", "op": "gt", "value": "4"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "alpha" not in resp.text
    assert "bravo" in resp.text


def test_add_enum_filter(client, login):
    _seed(client, login)
    _advanced_view(client)
    resp = client.post(
        "/views/1/filters",
        data={"action": "add", "col": "base:status", "op": "eq", "value": "retired"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "alpha" not in resp.text
    assert "bravo" in resp.text


def test_remove_and_clear_filters(client, login):
    _seed(client, login)
    _advanced_view(client)
    for col, value in [("base:name", "alpha"), ("base:name", "bravo")]:
        client.post(
            "/views/1/filters",
            data={"action": "add", "col": col, "op": "eq", "value": value},
            headers={"HX-Request": "true"},
        )
    resp = client.post(
        "/views/1/filters",
        data={"action": "remove", "index": "0"},
        headers={"HX-Request": "true"},
    )
    assert "bravo" in resp.text  # remaining filter still matches bravo
    resp = client.post("/views/1/filters", data={"action": "clear"}, headers={"HX-Request": "true"})
    assert "alpha" in resp.text and "bravo" in resp.text


def test_set_op_toggles_global_operator(db_session, client, login):
    _seed(client, login)
    _advanced_view(client)
    for col, value in [("base:name", "alpha"), ("base:name", "bravo")]:
        client.post(
            "/views/1/filters",
            data={"action": "add", "col": col, "op": "eq", "value": value},
            headers={"HX-Request": "true"},
        )
    resp = client.post(
        "/views/1/filters",
        data={"action": "set_op", "filter_op": "or"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "alpha" in resp.text and "bravo" in resp.text
    assert get_view(db_session, 1).config.get("filter_op") == "or"


def test_filter_value_required(client, login):
    _seed(client, login)
    _advanced_view(client)
    resp = client.post(
        "/views/1/filters",
        data={"action": "add", "col": "base:name", "op": "eq", "value": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash_type=error" in resp.headers["location"]


def test_non_htmx_post_redirects(client, login):
    _seed(client, login)
    _advanced_view(client)
    resp = client.post(
        "/views/1/filters",
        data={"action": "add", "col": "quick", "value": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_viewer_cannot_manage_filters(client, login):
    _seed(client, login)
    _advanced_view(client)
    client.post(
        "/users",
        data={"username": "viewer1", "password": "pw123456", "display_name": "V", "role": "viewer"},
        follow_redirects=False,
    )
    client.post("/logout", follow_redirects=False)
    login(username="viewer1", password="pw123456")
    resp = client.post("/views/1/filters", data={"action": "clear"}, follow_redirects=False)
    assert resp.status_code == 403


def test_update_view_preserves_advanced_filters(client, login):
    _seed(client, login)
    _advanced_view(client)
    client.post(
        "/views/1/filters",
        data={"action": "add", "col": "base:name", "op": "eq", "value": "alpha"},
        headers={"HX-Request": "true"},
    )
    # Edit the view (checkbox still on; standard filter rows disabled/submitted empty).
    client.post(
        "/views/1/edit",
        data={
            "name": "V",
            "advanced_filter": "on",
            "filter_slug": "",
            "filter_op": "",
            "filter_value": "",
        },
        follow_redirects=False,
    )
    html = client.get("/views/1").text
    assert "alpha" in html
    assert "bravo" not in html


def test_edit_form_renders_checkbox_state(client, login):
    _seed(client, login)
    _advanced_view(client)
    html = client.get("/views/1/edit").text
    assert 'name="advanced_filter"' in html
    assert 'id="advanced-filter-toggle"' in html
    assert "checked" in html
    assert 'id="filters-section"' in html
