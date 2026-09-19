"""HTTP tests for record CRUD routes (validation and 404s)."""


def _seed_server(client, login):
    login()
    assert (
        client.post("/entities", data={"name": "Server"}, follow_redirects=False).status_code == 303
    )
    assert (
        client.post(
            "/entities/1/attributes",
            data={"name": "Name", "data_type": "text", "is_required": "on"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/1/attributes",
            data={"name": "Cores", "data_type": "integer"},
            follow_redirects=False,
        ).status_code
        == 303
    )


def test_records_index(client, login):
    _seed_server(client, login)
    assert client.get("/entities/1/records").status_code == 200


def test_records_export(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01", "cores": "8"}, follow_redirects=False)
    resp = client.get("/entities/1/records/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="server-records.csv"' in resp.headers["content-disposition"]
    body = resp.text.lstrip("\ufeff")
    assert body.startswith("Name,Cores")
    assert "web01,8" in body


def test_records_export_404(client, login):
    login()
    assert client.get("/entities/9999/records/export").status_code == 404


def test_records_import_page(client, login):
    _seed_server(client, login)
    assert client.get("/entities/1/records/import").status_code == 200


def test_records_import_page_has_drop_zone(client, login):
    _seed_server(client, login)
    html = client.get("/entities/1/records/import").text
    assert 'id="drop-zone"' in html
    assert 'id="import-file"' in html
    assert 'accept=".csv,text/csv"' in html
    assert "Drag &amp; drop a CSV file here" in html
    # The raw file input is hidden; the drop zone is the visible control.
    assert 'class="hidden"' in html
    # Help text documents the composite key separator.
    assert "NAS-01 ^ Synology" in html


def test_records_import_without_file_flashes(client, login):
    _seed_server(client, login)
    resp = client.post("/entities/1/records/import", follow_redirects=True)
    assert resp.status_code == 200
    assert "no file selected" in resp.text


def test_records_import_upserts_when_entity_has_key(client, login):
    _seed_server(client, login)
    # Make the existing Name attribute (id 1) the entity key.
    client.post(
        "/attributes/1/edit",
        data={"name": "Name", "data_type": "text", "is_key": "on"},
        follow_redirects=False,
    )
    client.post("/entities/1/records", data={"name": "web01", "cores": "4"}, follow_redirects=False)
    resp = client.post(
        "/entities/1/records/import",
        files={"file": ("servers.csv", b"Name,Cores\nweb01,8\nweb02,16\n", "text/csv")},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Imported 1 record(s) and updated 1." in resp.text
    # web01 was updated (cores 8), web02 created (cores 16). Cells are
    # wrapped in .cell-wrap/.cell-value spans (link/copy-button support).
    assert "web01" in resp.text
    assert "web02" in resp.text
    assert 'class="cell-value">8</span>' in resp.text
    assert 'class="cell-value">16</span>' in resp.text


def test_records_import_success(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/entities/1/records/import",
        files={"file": ("servers.csv", b"Name,Cores\nweb01,8\nweb02,16\n", "text/csv")},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Imported 2 record(s)." in resp.text
    assert "web01" in resp.text
    assert "web02" in resp.text


def test_records_import_invalid_row_rolls_back(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "existing"}, follow_redirects=False)
    resp = client.post(
        "/entities/1/records/import",
        files={"file": ("servers.csv", b"Name,Cores\nweb01,8\nweb02,oops\n", "text/csv")},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "web01" not in resp.text  # all-or-nothing
    assert "Import aborted" in resp.text
    assert "Row 3" in resp.text


def test_records_import_missing_required_column(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/entities/1/records/import",
        files={"file": ("servers.csv", b"Cores\n8\n", "text/csv")},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Missing required column" in resp.text


def test_records_index_404(client, login):
    _seed_server(client, login)
    assert client.get("/entities/9999/records").status_code == 404


def test_new_record_page(client, login):
    _seed_server(client, login)
    assert client.get("/entities/1/records/new").status_code == 200


def test_create_record_success(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/entities/1/records", data={"name": "web01", "cores": "8"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "web01" in client.get("/entities/1/records").text


def test_create_record_missing_required(client, login):
    _seed_server(client, login)
    resp = client.post("/entities/1/records", data={"cores": "8"}, follow_redirects=False)
    assert resp.status_code == 400


def test_create_record_invalid_value(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/entities/1/records", data={"name": "web01", "cores": "abc"}, follow_redirects=False
    )
    assert resp.status_code == 400


def test_edit_record_page(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    assert client.get("/records/1/edit").status_code == 200


def test_edit_record_page_404(client, login):
    _seed_server(client, login)
    assert client.get("/records/9999/edit").status_code == 404


def test_update_record_success(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01", "cores": "8"}, follow_redirects=False)
    resp = client.post(
        "/records/1/edit", data={"name": "web01", "cores": "16"}, follow_redirects=False
    )
    assert resp.status_code == 303


def test_update_record_missing_required(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    resp = client.post("/records/1/edit", data={"cores": "8"}, follow_redirects=False)
    assert resp.status_code == 400


def test_update_record_404(client, login):
    _seed_server(client, login)
    resp = client.post("/records/9999/edit", data={"name": "x"}, follow_redirects=False)
    assert resp.status_code == 404


def test_delete_record(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    assert client.post("/records/1/delete", follow_redirects=False).status_code == 303
    # Soft-deleted: no longer listed.
    assert "web01" not in client.get("/entities/1/records").text


def test_delete_record_404(client, login):
    _seed_server(client, login)
    assert client.post("/records/9999/delete", follow_redirects=False).status_code == 404


def test_record_form_renders_attribute_hint(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text", "hint": "FQDN of the server."},
        follow_redirects=False,
    )
    html = client.get("/entities/1/records/new").text
    assert "FQDN of the server." in html
    assert 'class="hint"' in html


def test_record_form_preserves_multiline_hint(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Hostname", "data_type": "text", "hint": "First line\nSecond line"},
        follow_redirects=False,
    )
    html = client.get("/entities/1/records/new").text
    assert "First line\nSecond line" in html  # newline survives to the markup


def test_record_list_shows_system_columns(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    html = client.get("/entities/1/records").text
    assert "Created at" in html
    assert "Created by" in html
    assert "Last modified at" in html
    assert "Last modified by" in html


def test_record_edit_form_shows_metadata(client, login):
    _seed_server(client, login)
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    html = client.get("/records/1/edit").text
    assert "Record metadata" in html
    assert "admin" in html  # created_by resolves to the admin username


def test_inactive_attribute_hidden_from_record_form(client, login):
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
        "/attributes/2/edit",
        data={"name": "Cores", "data_type": "integer", "is_active": "false"},
        follow_redirects=False,
    )
    html = client.get("/entities/1/records/new").text
    assert "Name" in html
    assert "Cores" not in html


def test_new_record_form_prefills_default_values(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Name", "data_type": "text", "default_value": "web01"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/attributes",
        data={"name": "Cores", "data_type": "integer", "default_value": "8"},
        follow_redirects=False,
    )
    html = client.get("/entities/1/records/new").text
    assert 'value="web01"' in html
    assert 'value="8"' in html


def _seed_reference_many(client, login):
    login()
    client.post("/entities", data={"name": "Rack"}, follow_redirects=False)
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "rack-01"}, follow_redirects=False)
    client.post("/entities/1/records", data={"name": "rack-02"}, follow_redirects=False)
    client.post(
        "/entities/2/attributes",
        data={
            "name": "Racks",
            "data_type": "reference",
            "reference_entity_id": "1",
            "cardinality": "many",
        },
        follow_redirects=False,
    )


def test_record_form_renders_multi_reference_widget(client, login):
    _seed_reference_many(client, login)
    html = client.get("/entities/2/records/new").text
    assert 'class="multi-ref"' in html
    assert "data-add" in html
    assert "rack-01" in html  # available options in the source select
    assert "rack-02" in html


def test_create_record_with_multi_reference(client, login):
    _seed_reference_many(client, login)
    resp = client.post(
        "/entities/2/records",
        data={"racks": ["1", "2"]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    html = client.get("/entities/2/records").text
    assert "rack-01" in html
    assert "rack-02" in html


def test_record_edit_shows_selected_reference_chips(client, login):
    _seed_reference_many(client, login)
    client.post("/entities/2/records", data={"racks": ["1", "2"]}, follow_redirects=False)
    html = client.get("/records/3/edit").text
    assert 'class="chip"' in html
    assert 'name="racks"' in html  # hidden inputs carry the selected values
    assert "data-remove" in html
    assert "rack-01" in html
    assert "rack-02" in html


def _seed_link_server(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Console", "data_type": "link", "with_copy_button": "on"},
        follow_redirects=False,
    )


def test_record_form_renders_url_input(client, login):
    _seed_link_server(client, login)
    html = client.get("/entities/1/records/new").text
    assert 'type="url" name="console"' in html
    # The copy button is rendered but hidden: a new record's field is empty, so
    # there is nothing to copy (app.js reveals it as soon as something is typed).
    assert 'class="copy-btn hidden"' in html
    assert 'name="with_copy_button"' not in html


def test_link_attribute_accepts_valid_url(client, login):
    _seed_link_server(client, login)
    resp = client.post(
        "/entities/1/records",
        data={"console": "https://panel.example.com:8443/?a=1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_link_attribute_rejects_invalid_url(client, login):
    _seed_link_server(client, login)
    resp = client.post("/entities/1/records", data={"console": "not-a-url"}, follow_redirects=False)
    assert resp.status_code == 400
    assert "valid http(s) URL" in resp.text


def test_records_list_renders_link_as_anchor_with_copy_button(client, login):
    _seed_link_server(client, login)
    client.post(
        "/entities/1/records",
        data={"console": "https://panel.example.com"},
        follow_redirects=False,
    )
    html = client.get("/entities/1/records").text
    assert (
        '<a href="https://panel.example.com" target="_blank" rel="noopener">https://panel.example.com</a>'
        in html
    )
    assert 'class="copy-btn"' in html


def test_grid_copy_button_only_rendered_for_non_empty_cells(client, login):
    _seed_link_server(client, login)
    client.post(
        "/entities/1/records",
        data={"console": "https://panel.example.com"},
        follow_redirects=False,
    )
    client.post("/entities/1/records", data={}, follow_redirects=False)
    html = client.get("/entities/1/records").text
    # Only the record that has a Console URL gets a copy button.
    assert html.count('class="copy-btn"') == 1
    assert '<span class="cell-value">—</span>' in html


def test_record_form_copy_button_hidden_while_its_field_is_empty(client, login):
    _seed_link_server(client, login)
    client.post(
        "/entities/1/records",
        data={"console": "https://panel.example.com"},
        follow_redirects=False,
    )
    # New record: the field is empty, so the button is rendered hidden (app.js
    # reveals it while typing) rather than shown with nothing to copy.
    assert 'class="copy-btn hidden"' in client.get("/entities/1/records/new").text
    # Existing value: visible.
    edit_html = client.get("/records/1/edit").text
    assert 'class="copy-btn"' in edit_html
    assert 'class="copy-btn hidden"' not in edit_html


# --------------------------------------------------------------------------- #
# Source-aware redirects: the record form and row actions carry a `next`
# target, so add/edit/delete return to the page they were started from
# (default: the entity's records list).
# --------------------------------------------------------------------------- #


def _target(location: str) -> str:
    """Redirect target with the flash query string stripped."""
    return location.split("?")[0]


def _seed_record(client):
    client.post("/entities/1/records", data={"name": "web01", "cores": "8"}, follow_redirects=False)


def test_create_record_returns_to_the_source_page(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/entities/1/records",
        data={"name": "web01", "cores": "8", "next": "/views/1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _target(resp.headers["location"]) == "/views/1"


def test_update_record_returns_to_the_source_page(client, login):
    _seed_server(client, login)
    _seed_record(client)
    resp = client.post(
        "/records/1/edit",
        data={"name": "web02", "cores": "4", "next": "/views/3"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _target(resp.headers["location"]) == "/views/3"


def test_delete_record_returns_to_the_source_page(client, login):
    _seed_server(client, login)
    _seed_record(client)
    resp = client.post("/records/1/delete", data={"next": "/views/2"}, follow_redirects=False)
    assert resp.status_code == 303
    assert _target(resp.headers["location"]) == "/views/2"


def test_record_mutations_default_to_the_records_list(client, login):
    _seed_server(client, login)
    _seed_record(client)
    resp = client.post("/records/1/delete", data={}, follow_redirects=False)
    assert _target(resp.headers["location"]) == "/entities/1/records"


def test_unsafe_next_targets_fall_back_to_the_records_list(client, login):
    _seed_server(client, login)
    # Each payload needs a fresh live record: deleting 1 twice is now a 404
    # (soft-deleted records are immutable).
    for payload in (
        "//evil.example.com",
        "https://evil.example.com",
        "/\\evil.example.com",
        "evil.example.com",
    ):
        _seed_record(client)
        list_page = client.get("/entities/1/records").text
        import re as _re

        match = _re.search(r"/records/(\d+)/delete", list_page)
        assert match, "no delete link found on the records page"
        record_id = match.group(1)
        resp = client.post(
            f"/records/{record_id}/delete", data={"next": payload}, follow_redirects=False
        )
        assert resp.status_code == 303
        assert _target(resp.headers["location"]) == "/entities/1/records", payload


def test_soft_deleted_record_mutations_return_404(client, login):
    _seed_server(client, login)
    _seed_record(client)
    assert client.post("/records/1/delete", data={}, follow_redirects=False).status_code == 303
    # The record still exists in the DB, but it is deleted — no re-delete,
    # no edit.
    assert client.post("/records/1/delete", data={}, follow_redirects=False).status_code == 404
    resp = client.post("/records/1/edit", data={"name": "x"}, follow_redirects=False)
    assert resp.status_code == 404


def test_new_record_form_carries_the_return_target(client, login):
    _seed_server(client, login)
    html = client.get("/entities/1/records/new", params={"next": "/views/4"}).text
    assert '<input type="hidden" name="next" value="/views/4">' in html
    assert "Back to view" in html


def test_edit_record_form_carries_the_return_target(client, login):
    _seed_server(client, login)
    _seed_record(client)
    html = client.get("/records/1/edit", params={"next": "/views/4"}).text
    assert '<input type="hidden" name="next" value="/views/4">' in html


def test_record_form_defaults_to_the_records_list(client, login):
    _seed_server(client, login)
    html = client.get("/entities/1/records/new").text
    assert '<input type="hidden" name="next" value="/entities/1/records">' in html
    assert "Back to records" in html


def test_record_form_keeps_the_source_after_a_validation_error(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/entities/1/records",
        data={"name": "", "cores": "8", "next": "/views/9"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert '<input type="hidden" name="next" value="/views/9">' in resp.text
