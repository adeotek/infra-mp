"""Sortable data-grid markup tests.

Data grids render with ``data-sortable`` so the vanilla-JS header-click
sorting kicks in, and action columns are marked ``no-sort``. Grids that
offer drag-and-drop reordering (attributes, dashboard widgets config)
deliberately do NOT get header sorting.
"""


def _seed_entity_with_record(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    client.post(
        "/entities/1/attributes", data={"name": "Name", "data_type": "text"}, follow_redirects=False
    )
    client.post("/entities/1/records", data={"name": "web01"}, follow_redirects=False)


def test_entities_list_is_sortable(client, login):
    _seed_entity_with_record(client, login)
    html = client.get("/entities").text
    assert "data-sortable" in html
    assert 'data-grid-key="entities"' in html
    assert "no-sort" in html  # the Open column


def test_users_list_is_sortable(client, login):
    login()
    html = client.get("/users").text
    assert "data-sortable" in html
    assert 'data-grid-key="users"' in html
    assert "no-sort" in html  # the actions column


def test_views_list_is_sortable(client, login):
    _seed_entity_with_record(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    html = client.get("/views").text
    assert "data-sortable" in html
    assert 'data-grid-key="views"' in html


def test_records_list_is_sortable(client, login):
    _seed_entity_with_record(client, login)
    html = client.get("/entities/1/records").text
    assert "data-sortable" in html
    assert 'data-grid-key="records-1"' in html
    assert "no-sort" in html  # the actions column
    # Quick search filter wiring.
    assert 'data-filter-table="records-table"' in html
    assert 'id="records-table"' in html
    assert ">Apply<" in html
    assert ">Clear<" in html


def test_attributes_grid_reorderable_but_not_sortable(client, login):
    _seed_entity_with_record(client, login)
    client.post(
        "/entities/1/attributes",
        data={"name": "Cores", "data_type": "integer"},
        follow_redirects=False,
    )
    html = client.get("/entities/1").text
    # Drag-and-drop reorder grids get no header-click sorting.
    assert "data-sortable" not in html
    assert "data-grid-key" not in html
    assert 'data-reorder-url="/entities/1/attributes/reorder"' in html


def test_view_detail_grid_is_sortable(client, login):
    _seed_entity_with_record(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    html = client.get("/views/1").text
    assert "data-sortable" in html
    assert 'data-grid-key="view-1"' in html


def test_dashboard_config_table_reorderable_but_not_sortable(client, login):
    _seed_entity_with_record(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard/config").text
    # Drag-and-drop reorder grids get no header-click sorting.
    assert "data-sortable" not in html
    assert "data-grid-key" not in html
    assert 'data-reorder-url="/dashboard/widgets/reorder"' in html


def test_dashboard_widget_tables_are_sortable(client, login):
    _seed_entity_with_record(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "table", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert "data-sortable" in html
    assert 'data-grid-key="dashboard-widget-1"' in html


def test_ui_state_bootstrap_is_rendered(client, login):
    login()
    html = client.get("/dashboard").text
    # The <head> script applies persisted section collapse before first paint.
    assert "inframp-ui-state" in html
    assert "window.__inframpUIState" in html


def test_sidebar_sections_are_collapsible(client, login):
    login()
    html = client.get("/dashboard").text
    for section in ("data", "views", "config"):
        assert f'data-section="{section}"' in html
        assert f'id="nav-section-{section}"' in html
    assert html.count("section-chevron") == 3
    assert 'aria-expanded="true"' in html
