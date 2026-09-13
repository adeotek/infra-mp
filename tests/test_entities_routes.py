"""HTTP tests for entity and attribute (schema) routes."""

import re


def test_entities_index(client, login):
    login()
    assert client.get("/entities").status_code == 200


def test_entities_list_action_buttons(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    html = client.get("/entities").text
    assert ">Open<" not in html
    # Edit first (schema managers only), then the records link.
    assert 'hx-get="/entities/1/edit"' in html
    assert 'title="Edit"' in html
    assert 'href="/entities/1/records" class="action-btn"' in html
    assert 'title="Records" aria-label="Records"' in html


def test_attribute_form_has_key_checkbox(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    assert 'name="is_key"' in client.get("/entities/1/attributes/new").text


def test_attribute_key_flag_shows_in_grid(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Name", "data_type": "text", "is_key": "on"},
        follow_redirects=False,
    )
    html = client.get("/entities/1").text
    assert "<th>Key</th>" in html
    # Name: Key=Yes and Active=Yes are the two Yes cells.
    assert html.count("<td>Yes</td>") == 2


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


def test_entity_detail_shows_unique_column(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text", "is_unique": "on"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/attributes",
        data={"name": "Cores", "data_type": "integer"},
        follow_redirects=False,
    )
    html = client.get("/entities/1").text
    assert "<th>Unique</th>" in html
    # Yes cells: Hostname (Unique + Active) and Cores (Active only).
    assert html.count("<td>Yes</td>") == 3


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


def test_attribute_form_has_copy_button_checkbox(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    html = client.get("/entities/1/attributes/new").text
    assert 'name="with_copy_button"' in html


def test_attribute_form_offers_link_type(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    html = client.get("/entities/1/attributes/new").text
    assert '<option value="link"' in html


def test_attribute_detail_shows_copy_column(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Console", "data_type": "link", "with_copy_button": "on"},
        follow_redirects=False,
    )
    html = client.get("/entities/1").text
    assert "<th>Copy</th>" in html
    # Type cell, then Required(—) · Unique(—) · Copy(Yes); template
    # newlines between cells make a whitespace-stripped comparison safer.
    compact = re.sub(r">\s+<", "><", html)
    assert "<td><code>link</code></td><td>—</td><td>—</td><td>Yes</td>" in compact


def test_copy_button_flag_editable_with_records(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "IP", "data_type": "text"},
        follow_redirects=False,
    )
    assert (
        client.post(
            "/entities/1/records", data={"ip": "10.0.0.1"}, follow_redirects=False
        ).status_code
        == 303
    )
    # Display-only flag: flipping it after records exist is allowed.
    resp = client.post(
        "/attributes/1/edit",
        data={"name": "IP", "data_type": "text", "with_copy_button": "on"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    html = client.get("/entities/1").text
    # Type cell, then Required(—) · Unique(—) · Copy(Yes); template
    # newlines between cells make a whitespace-stripped comparison safer.
    compact = re.sub(r">\s+<", "><", html)
    assert "<td><code>text</code></td><td>—</td><td>—</td><td>Yes</td>" in compact


# --------------------------------------------------------------------------- #
# Data-type conversions from the edit form
# --------------------------------------------------------------------------- #


def _seed_panel_attribute(client, login, value: str = "https://console.example"):
    """Entity 1 with a text 'Panel' attribute and one record holding ``value``."""
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Panel", "data_type": "text"},
        follow_redirects=False,
    )
    client.post("/entities/1/records", data={"panel": value}, follow_redirects=False)


def _type_options(html: str) -> str:
    """The <option> markup of the attribute form's Type select."""
    return html.split('name="data_type"')[1].split("</select>")[0]


def test_text_to_link_conversion_with_records(client, login):
    _seed_panel_attribute(client, login)
    resp = client.post(
        "/attributes/1/edit", data={"name": "Panel", "data_type": "link"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "<code>link</code>" in client.get("/entities/1").text


def test_text_to_link_conversion_rejected_when_a_record_is_not_a_url(client, login):
    _seed_panel_attribute(client, login, value="see the docs")
    resp = client.post(
        "/attributes/1/edit", data={"name": "Panel", "data_type": "link"}, follow_redirects=False
    )
    assert resp.status_code == 400
    assert "not a valid http(s) URL" in resp.text
    assert "Nothing was changed" in resp.text
    # Rolled back: the attribute is still text.
    assert "<code>text</code>" in client.get("/entities/1").text


def test_textarea_to_text_conversion_rejected_on_a_multiline_record(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Note", "data_type": "textarea"},
        follow_redirects=False,
    )
    client.post("/entities/1/records", data={"note": "line one\nline two"}, follow_redirects=False)
    resp = client.post(
        "/attributes/1/edit", data={"name": "Note", "data_type": "text"}, follow_redirects=False
    )
    assert resp.status_code == 400
    assert "would truncate" in resp.text
    assert "<code>textarea</code>" in client.get("/entities/1").text


def test_attribute_form_disables_unconvertible_types_with_records(client, login):
    _seed_panel_attribute(client, login)
    options = _type_options(client.get("/attributes/1/edit").text)
    assert '<option value="text" selected>text</option>' in options
    assert '<option value="link">link</option>' in options
    assert '<option value="textarea">textarea</option>' in options
    assert '<option value="integer" disabled>integer</option>' in options
    assert '<option value="enum" disabled>enum</option>' in options


def test_attribute_form_offers_every_type_without_records(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Panel", "data_type": "text"},
        follow_redirects=False,
    )
    options = _type_options(client.get("/attributes/1/edit").text)
    assert '<option value="integer">integer</option>' in options
    assert "disabled" not in options


# --------------------------------------------------------------------------- #
# Attribute form layout
# --------------------------------------------------------------------------- #


def test_checkbox_help_renders_below_the_checkbox(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    html = client.get("/entities/1/attributes/new").text
    # Not inline in the checkbox row any more...
    assert "Unique <span" not in html
    assert "Key <span" not in html
    # ...but a sibling of the checkbox label, wrapped onto its own line by CSS.
    assert 'class="checkbox-label has-help"' in html
    assert '<span class="checkbox-help muted">Values must be unique across records.</span>' in html
    assert '<span class="checkbox-help muted">Part of the entity key' in html
    assert '<span class="checkbox-help muted">Renders a copy icon' in html

    css = client.get("/static/style.css").text
    assert ".checkbox-label.has-help { flex-wrap: wrap;" in css
    assert "flex-basis: 100%" in css.split(".checkbox-help {")[1].split("}")[0]


def test_attribute_form_modal_is_ten_percent_wider(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    html = client.get("/entities/1/attributes/new").text
    assert 'class="attribute-form"' in html
    # 520px default modal * 1.1.
    assert (
        ".modal:has(.attribute-form) { max-width: 572px; }" in client.get("/static/style.css").text
    )
