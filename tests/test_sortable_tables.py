"""Sortable data-grid markup tests.

Every data grid renders with ``data-sortable`` so the vanilla-JS header-click
sorting kicks in, and action/drag-handle columns are marked ``no-sort``.
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
    assert "no-sort" in html  # the Open column


def test_users_list_is_sortable(client, login):
    login()
    html = client.get("/users").text
    assert "data-sortable" in html
    assert "no-sort" in html  # the actions column


def test_views_list_is_sortable(client, login):
    _seed_entity_with_record(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    assert "data-sortable" in client.get("/views").text


def test_records_list_is_sortable(client, login):
    _seed_entity_with_record(client, login)
    html = client.get("/entities/1/records").text
    assert "data-sortable" in html
    assert "no-sort" in html  # the actions column


def test_attributes_grid_is_sortable_and_reorderable(client, login):
    _seed_entity_with_record(client, login)
    client.post(
        "/entities/1/attributes",
        data={"name": "Cores", "data_type": "integer"},
        follow_redirects=False,
    )
    html = client.get("/entities/1").text
    assert "data-sortable" in html
    assert 'data-reorder-url="/entities/1/attributes/reorder"' in html
    assert "no-sort" in html  # grip + actions columns


def test_view_detail_grid_is_sortable(client, login):
    _seed_entity_with_record(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    assert "data-sortable" in client.get("/views/1").text


def test_dashboard_config_table_is_sortable_and_reorderable(client, login):
    _seed_entity_with_record(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "count", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    html = client.get("/dashboard/config").text
    assert "data-sortable" in html
    assert 'data-reorder-url="/dashboard/widgets/reorder"' in html
    assert "no-sort" in html  # grip + actions columns


def test_dashboard_widget_tables_are_sortable(client, login):
    _seed_entity_with_record(client, login)
    client.post(
        "/dashboard/widgets",
        data={"title": "W", "widget_type": "table", "entity_id": "1", "view_id": ""},
        follow_redirects=False,
    )
    assert "data-sortable" in client.get("/dashboard").text
