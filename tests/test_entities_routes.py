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


def test_delete_attribute_blocked_when_records_exist(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    resp = client.post("/attributes/1/delete", follow_redirects=False)
    assert resp.status_code == 303
    # Attribute still exists (deletion rejected with a flash error).
    assert "Name" in client.get("/entities/1").text


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
