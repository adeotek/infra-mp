"""Mobile layout: off-canvas sidebar drawer, hamburger, stacked grids."""


def test_base_layout_has_mobile_drawer_controls(client, login):
    login()
    html = client.get("/dashboard").text
    assert 'id="mobile-menu-btn"' in html
    assert 'id="sidebar-backdrop"' in html
    assert "fa-bars" in html


def test_login_page_has_no_drawer_controls(client):
    html = client.get("/login").text
    assert 'id="mobile-menu-btn"' not in html


def test_mobile_css_rules_are_served(client, login):
    login()
    css = client.get("/static/style.css").text
    assert "@media (max-width: 768px)" in css
    assert "body.sidebar-open .sidebar" in css
    assert ".mobile-menu-btn" in css
    assert ".sidebar-backdrop" in css
    # Tables keep their horizontal-scroll wrapper on phones.
    assert "grid-template-columns: 1fr" in css


def test_mobile_js_toggle_is_served(client, login):
    login()
    js = client.get("/static/app.js").text
    assert "sidebar-open" in js
    assert "mobile-menu-btn" in js
