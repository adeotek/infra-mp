"""HTTP tests for entity and attribute (schema) routes."""


def test_entities_index(client, login):
    login()
    assert client.get("/entities").status_code == 200


def test_new_entity_page(client, login):
    login()
    assert client.get("/entities/new").status_code == 200


def test_create_entity(client, login):
    login()
    resp = client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "Server" in client.get("/entities").text


def test_create_entity_duplicate(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    assert resp.status_code == 400


def test_entity_detail(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    assert client.get("/entities/1").status_code == 200


def test_entity_detail_404(client, login):
    login()
    assert client.get("/entities/9999").status_code == 404


def test_edit_entity_page(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    assert client.get("/entities/1/edit").status_code == 200


def test_update_entity(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.post("/entities/1/edit", data={"name": "Server Renamed"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "Server Renamed" in client.get("/entities").text


def test_update_entity_duplicate(client, login):
    login()
    client.post("/entities", data={"name": "A"}, follow_redirects=False)
    client.post("/entities", data={"name": "B"}, follow_redirects=False)
    resp = client.post("/entities/1/edit", data={"name": "B"}, follow_redirects=False)
    assert resp.status_code == 400


def test_delete_entity(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    assert client.post("/entities/1/delete", follow_redirects=False).status_code == 303
    assert client.get("/entities/1").status_code == 404


def test_new_attribute_page(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    assert client.get("/entities/1/attributes/new").status_code == 200


def test_new_attribute_page_404(client, login):
    login()
    assert client.get("/entities/9999/attributes/new").status_code == 404


def test_create_attribute(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_create_attribute_enum_without_options(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.post(
        "/entities/1/attributes",
        data={"name": "Status", "data_type": "enum"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_create_reference_attribute_many(client, login):
    login()
    client.post("/entities", data={"name": "Rack"}, follow_redirects=False)
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.post(
        "/entities/2/attributes",
        data={
            "name": "Racks",
            "data_type": "reference",
            "reference_entity_id": "1",
            "cardinality": "many",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_edit_attribute_page(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text"},
        follow_redirects=False,
    )
    assert client.get("/attributes/1/edit").status_code == 200


def test_update_attribute(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text"},
        follow_redirects=False,
    )
    resp = client.post(
        "/attributes/1/edit", data={"name": "Host", "data_type": "text"}, follow_redirects=False
    )
    assert resp.status_code == 303


def test_delete_attribute(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text"},
        follow_redirects=False,
    )
    assert client.post("/attributes/1/delete", follow_redirects=False).status_code == 303


def test_delete_attribute_404(client, login):
    login()
    assert client.post("/attributes/9999/delete", follow_redirects=False).status_code == 404


def test_create_attribute_with_hint(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text", "hint": "FQDN of the server."},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # Hint is persisted and shown on the edit form.
    assert "FQDN of the server." in client.get("/attributes/1/edit").text


def test_attribute_form_has_hint_field(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    html = client.get("/entities/1/attributes/new").text
    assert 'name="hint"' in html


def test_update_attribute_slug_via_post(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text"},
        follow_redirects=False,
    )
    resp = client.post(
        "/attributes/1/edit",
        data={"name": "Hostname", "data_type": "text", "slug": "fqdn"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "(fqdn)" in client.get("/entities/1").text


def test_delete_attribute_with_records(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    resp = client.post("/attributes/1/delete", follow_redirects=False)
    assert resp.status_code == 303
    # Attribute is deleted even though the entity has records.
    assert "No attributes yet" in client.get("/entities/1").text


def test_delete_button_shown_when_records_exist(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    html = client.get("/entities/1").text
    assert "/attributes/1/delete" in html
    assert "remove its value from all records" in html


def test_delete_attribute_removes_value_from_record(client, login):
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
    client.post("/entities/1/records", data={"name": "web01", "cores": "8"}, follow_redirects=False)
    client.post("/attributes/1/delete", follow_redirects=False)  # delete "Name"
    rec_html = client.get("/entities/1/records").text
    assert "web01" not in rec_html  # deleted attribute's value removed
    assert "Cores" in rec_html  # remaining attribute intact


def test_inactivate_optional_attribute(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Note", "data_type": "text"}, follow_redirects=False
    )
    # Submit "is_active=false" -> the attribute is inactivated.
    client.post(
        "/attributes/1/edit",
        data={"name": "Note", "data_type": "text", "is_active": "false"},
        follow_redirects=False,
    )
    html = client.get("/entities/1/records/new").text
    assert "Note" not in html


def test_update_entity_slug_via_post(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.post(
        "/entities/1/edit",
        data={"name": "Server", "slug": "server-renamed"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "server-renamed" in client.get("/entities/1").text


def _seed_three_attributes(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    for name in ("Name", "IP", "Role"):
        client.post(
            "/entities/1/attributes",
            data={"name": name, "data_type": "text"},
            follow_redirects=False,
        )


def test_reorder_attributes(client, login):
    _seed_three_attributes(client, login)
    resp = client.post("/entities/1/attributes/reorder", data={"order": "3,1,2"})
    assert resp.status_code == 204
    html = client.get("/entities/1").text
    assert html.index("(role)") < html.index("(name)") < html.index("(ip)")


def test_reorder_attributes_404(client, login):
    login()
    assert client.post("/entities/9999/attributes/reorder", data={"order": "1"}).status_code == 404


def test_reorder_attributes_invalid_order(client, login):
    _seed_three_attributes(client, login)
    resp = client.post("/entities/1/attributes/reorder", data={"order": "1"})
    assert resp.status_code == 400


def test_reorder_attributes_non_integer_order(client, login):
    _seed_three_attributes(client, login)
    resp = client.post("/entities/1/attributes/reorder", data={"order": "abc"})
    assert resp.status_code == 400


def test_entity_detail_has_drag_reorder_ui(client, login):
    _seed_three_attributes(client, login)
    html = client.get("/entities/1").text
    assert 'id="attributes-table"' in html
    assert 'data-reorder-url="/entities/1/attributes/reorder"' in html
    assert 'draggable="true"' in html


def test_edit_attribute_page_shows_enum_options(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Status", "data_type": "enum", "options": "running\nstopped"},
        follow_redirects=False,
    )
    html = client.get("/attributes/1/edit").text
    assert "running" in html
    assert "stopped" in html


def test_edit_attribute_page_shows_reference_cardinality(client, login):
    login()
    client.post("/entities", data={"name": "Rack"}, follow_redirects=False)
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/2/attributes",
        data={
            "name": "Rack",
            "data_type": "reference",
            "reference_entity_id": "1",
            "cardinality": "many",
        },
        follow_redirects=False,
    )
    html = client.get("/attributes/1/edit").text
    assert 'value="many" selected' in html


def test_attribute_form_has_unique_field(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    html = client.get("/entities/1/attributes/new").text
    assert 'name="is_unique"' in html


def test_unique_attribute_rejects_duplicate_record(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text", "is_unique": "on"},
        follow_redirects=False,
    )
    assert (
        client.post(
            "/entities/1/records", data={"hostname": "web1"}, follow_redirects=False
        ).status_code
        == 303
    )
    resp = client.post("/entities/1/records", data={"hostname": "web1"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "must be unique" in resp.text


def test_unique_attribute_rejects_duplicate_on_record_edit(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text", "is_unique": "on"},
        follow_redirects=False,
    )
    client.post("/entities/1/records", data={"hostname": "web1"}, follow_redirects=False)
    client.post("/entities/1/records", data={"hostname": "web2"}, follow_redirects=False)
    # Editing record 2 to take record 1's value is rejected...
    resp = client.post("/records/2/edit", data={"hostname": "web1"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "must be unique" in resp.text
    # ...but keeping its own value is fine.
    assert (
        client.post(
            "/records/2/edit", data={"hostname": "web2"}, follow_redirects=False
        ).status_code
        == 303
    )
