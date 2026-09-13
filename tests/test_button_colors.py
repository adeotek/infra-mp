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
    assert "color: var(--icon-primary-hover)" in hover
    assert "background: none" in hover


def _token(css: str, name: str) -> str:
    """The first (light-theme) declaration of a CSS custom property."""
    return css.split(f"{name}: ")[1].split(";")[0].strip()


def _relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of a #rrggbb colour."""

    def channel(value: int) -> float:
        srgb = value / 255
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(int(hex_color[i : i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_edit_icon_hover_blue_is_lighter_than_its_base(client, login):
    # Requirement, not a magic hex: the pencil must get LIGHTER on hover. The
    # button token --btn-primary-hover is darker in light theme, hence the
    # dedicated --icon-primary-hover.
    login()
    css = client.get("/static/style.css").text
    base = _token(css, "--btn-primary")
    hover = _token(css, "--icon-primary-hover")
    assert _relative_luminance(hover) > _relative_luminance(base), (base, hover)
    # Defined in both theme blocks so the icon hover is theme-independent.
    assert css.count(f"--icon-primary-hover: {hover}") == 2


def test_delete_icon_uses_the_lighter_accent_and_darkens_on_hover(client, login):
    login()
    css = client.get("/static/style.css").text
    base = css.split(".action-btn-danger {")[1].split("}")[0]
    # The accent red (lighter), not the darker --btn-danger button fill.
    assert "color: var(--danger)" in base
    hover = css.split(".action-btn-danger:hover {")[1].split("}")[0]
    assert "color: var(--icon-danger-hover)" in hover
    # The shared .action-btn:hover fill must not survive here.
    assert "background: none" in hover


def _theme_block(css: str, theme: str) -> str:
    """The declaration block of one theme (light = :root, dark = [data-theme])."""
    marker = ":root {" if theme == "light" else '[data-theme="dark"] {'
    return css.split(marker)[1].split("}")[0]


def _contrast_ratio(fg: str, bg: str) -> float:
    first, second = _relative_luminance(fg), _relative_luminance(bg)
    hi, lo = max(first, second), min(first, second)
    return (hi + 0.05) / (lo + 0.05)


def test_delete_icon_reds_are_light_to_dark_with_contrast_in_both_themes(client, login):
    # Requirement: lighter red at rest, darker on hover, and >= 3:1 for both
    # states against the backdrops the icon actually sits on (a row is --surface
    # at rest and --hover while hovered).
    login()
    css = client.get("/static/style.css").text
    for theme in ("light", "dark"):
        block = _theme_block(css, theme)
        rest = _token(block, "--danger")
        hover = _token(block, "--icon-danger-hover")
        assert _relative_luminance(hover) < _relative_luminance(rest), theme
        assert _contrast_ratio(rest, _token(block, "--surface")) >= 3.0, (theme, rest)
        assert _contrast_ratio(hover, _token(block, "--hover")) >= 3.0, (theme, hover)


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
