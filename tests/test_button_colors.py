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


def _seed_copy_attribute_grid(client, login):
    """Entity 1 with a copy-button attribute and one record, plus a saved view."""
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes",
        data={"name": "Console", "data_type": "link", "with_copy_button": "on"},
        follow_redirects=False,
    )
    client.post(
        "/entities/1/records", data={"console": "https://console.example"}, follow_redirects=False
    )
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)


def test_grid_copy_icon_is_regular_in_both_grids(client, login):
    _seed_copy_attribute_grid(client, login)
    for url in ("/entities/1/records", "/views/1"):
        html = client.get(url).text
        assert '<i class="fa-regular fa-copy"' in html, url
        assert "fa-solid fa-copy" not in html, url


def test_grid_copy_icon_is_teal_css(client, login):
    login()
    css = client.get("/static/style.css").text
    block = css.split(".cell-wrap .copy-btn {")[1].split("}")[0]
    assert "color: var(--btn-teal)" in block
    hover = css.split(".cell-wrap .copy-btn:hover {")[1].split("}")[0]
    assert "color: var(--btn-teal-hover)" in hover
