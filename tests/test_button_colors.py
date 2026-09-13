"""Button color convention tests.

Blue (``btn-primary``): Add/Create, Edit, Import.
Teal (``btn-teal``): Export, View.
Red (``btn-danger``): Delete.
Row action icons (``action-btn-edit`` / ``action-btn-danger``) reuse those fills
as icon colors and never paint a background of their own.
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


def test_edit_icon_is_the_primary_blue(client, login):
    login()
    css = client.get("/static/style.css").text
    base = css.split(".action-btn-edit {")[1].split("}")[0]
    assert "color: var(--btn-primary)" in base
    hover = css.split(".action-btn-edit:hover {")[1].split("}")[0]
    assert "color: var(--btn-primary-hover)" in hover
    assert "background: none" in hover


def test_delete_icon_is_the_danger_red_without_a_background(client, login):
    login()
    css = client.get("/static/style.css").text
    base = css.split(".action-btn-danger {")[1].split("}")[0]
    assert "color: var(--btn-danger)" in base
    hover = css.split(".action-btn-danger:hover {")[1].split("}")[0]
    # Darker red, derived exactly like the .btn-danger hover fill.
    assert "color: color-mix(in srgb, var(--btn-danger) 88%, #000)" in hover
    # The shared .action-btn:hover fill must not survive here.
    assert "background: none" in hover


def test_grid_action_icons_carry_the_color_classes(client, login):
    _seed_server(client, login)
    for url in ("/entities/1/records", "/entities/1"):
        html = client.get(url).text
        assert 'class="action-btn action-btn-edit"' in html, url
        assert 'class="action-btn action-btn-danger"' in html, url


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
