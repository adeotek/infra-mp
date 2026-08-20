"""Button color convention tests.

Blue (``btn-primary``): Add/Create, Edit, Import.
Teal (``btn-teal``): Export, View.
"""


def _seed_server(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)


def test_records_page_button_colors(client, login):
    _seed_server(client, login)
    html = client.get("/entities/1/records").text
    assert 'records/import" class="btn btn-primary"' in html
    assert 'class="btn btn-primary">Add record' in html
    assert 'class="btn btn-teal">Export CSV' in html


def test_import_modal_submit_is_blue(client, login):
    _seed_server(client, login)
    html = client.get("/entities/1/records/import").text
    assert 'class="btn btn-primary">Import</button>' in html


def test_entity_detail_button_colors(client, login):
    _seed_server(client, login)
    html = client.get("/entities/1").text
    assert 'class="btn btn-primary"' in html  # Edit
    assert 'class="btn btn-teal">View records' in html


def test_view_detail_button_colors(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    html = client.get("/views/1").text
    assert 'class="btn btn-primary">Edit view' in html
    assert 'class="btn btn-teal">Export CSV' in html


def test_edit_icons_hover_blue_css(client, login):
    # The edit pencil hover matches the default (blue) action hover.
    login()
    css = client.get("/static/style.css").text
    block = css.split(".action-btn-edit:hover")[1].split("}")[0]
    assert "color: var(--primary)" in block
