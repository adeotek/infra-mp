"""In-page confirmation dialog markup tests.

Destructive forms carry ``data-confirm`` (rendered in the app's own modal
dialog) instead of the browser's ``confirm()``.
"""


def _seed(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )


def test_entity_detail_uses_inpage_confirms(client, login):
    _seed(client, login)
    html = client.get("/entities/1").text
    assert "onsubmit" not in html
    assert html.count("data-confirm=") == 2  # entity delete + attribute delete
    assert "Delete this entity and all its records?" in html


def test_records_page_uses_inpage_confirm(client, login):
    _seed(client, login)
    html = client.get("/entities/1/records").text
    assert "onsubmit" not in html
    assert 'data-confirm="Delete this record?"' in html


def test_users_views_config_use_inpage_confirms(client, login):
    _seed(client, login)
    # A second user is needed: the current user's own row has no delete form.
    client.post(
        "/users",
        data={"username": "bob", "role": "viewer", "password": "password-123"},
        follow_redirects=False,
    )
    assert 'data-confirm="Delete this user?"' in client.get("/users").text
    assert 'data-confirm="Delete this view?"' in client.get("/views").text
    assert 'data-confirm="Remove this widget?"' in client.get("/dashboard/config").text


def test_backup_restore_uses_inpage_confirm(client, login):
    login()
    html = client.get("/settings/backup").text
    assert "Replace the current database with the uploaded backup?" in html
    assert "onsubmit" not in html


def test_confirm_dialog_is_rendered_on_every_page(client, login):
    login()
    for path in ("/dashboard", "/entities", "/settings/backup", "/login"):
        html = client.get(path).text
        assert 'id="confirm-dialog"' in html
        assert 'id="confirm-message"' in html
        assert 'id="confirm-cancel"' in html
        assert 'id="confirm-ok"' in html
