"""HTTP tests for saved-view routes (CRUD, validation, and 404s)."""


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
    assert (
        client.post(
            "/entities/1/attributes",
            data={"name": "Status", "data_type": "enum", "options": "active\nretired"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    for name, cores in [("alpha", "4"), ("bravo", "8")]:
        assert (
            client.post(
                "/entities/1/records",
                data={"name": name, "cores": cores, "status": "active"},
                follow_redirects=False,
            ).status_code
            == 303
        )


def test_views_index_renders(client, login):
    _seed_server(client, login)
    assert client.get("/views").status_code == 200


def test_new_view_choose_entity(client, login):
    _seed_server(client, login)
    assert client.get("/views/new").status_code == 200


def test_new_view_with_entity(client, login):
    _seed_server(client, login)
    assert client.get("/views/new", params={"entity_id": 1}).status_code == 200


def test_new_view_missing_entity_404(client, login):
    _seed_server(client, login)
    assert client.get("/views/new", params={"entity_id": 9999}).status_code == 404


def test_create_view(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/views",
        data={
            "name": "Active Servers",
            "entity_id": "1",
            "columns": ["name", "cores"],
            "sort_slug": "cores",
            "sort_dir": "desc",
            "filter_slug": ["status"],
            "filter_op": ["eq"],
            "filter_value": ["active"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/views/1" in resp.headers["location"]


def test_create_view_requires_name(client, login):
    _seed_server(client, login)
    resp = client.post("/views", data={"name": "", "entity_id": "1"}, follow_redirects=False)
    assert resp.status_code == 400


def test_create_view_missing_entity_404(client, login):
    _seed_server(client, login)
    resp = client.post("/views", data={"name": "X", "entity_id": "9999"}, follow_redirects=False)
    assert resp.status_code == 404


def test_view_detail(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    assert client.get("/views/1").status_code == 200


def test_view_detail_404(client, login):
    _seed_server(client, login)
    assert client.get("/views/9999").status_code == 404


def test_edit_view_page(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    assert client.get("/views/1/edit").status_code == 200


def test_edit_view_page_404(client, login):
    _seed_server(client, login)
    assert client.get("/views/9999/edit").status_code == 404


def test_update_view(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    resp = client.post(
        "/views/1/edit", data={"name": "Renamed", "entity_id": "1"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "Renamed" in client.get("/views/1").text


def test_update_view_requires_name(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    resp = client.post("/views/1/edit", data={"name": "", "entity_id": "1"}, follow_redirects=False)
    assert resp.status_code == 400


def test_delete_view(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "V", "entity_id": "1"}, follow_redirects=False)
    assert client.post("/views/1/delete", follow_redirects=False).status_code == 303
    assert client.get("/views/1").status_code == 404


def test_delete_view_404(client, login):
    _seed_server(client, login)
    assert client.post("/views/9999/delete", follow_redirects=False).status_code == 404


def _seed_with_references(client, login):
    """Site (1) <- Rack (2) <- Server (3); one record chain S1 <- R1 <- A."""
    login()
    for name in ["Site", "Rack", "Server"]:
        assert (
            client.post("/entities", data={"name": name}, follow_redirects=False).status_code == 303
        )
    assert (
        client.post(
            "/entities/1/attributes",
            data={"name": "Name", "data_type": "text"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/2/attributes",
            data={"name": "Name", "data_type": "text"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/2/attributes",
            data={
                "name": "Site",
                "data_type": "reference",
                "reference_entity_id": "1",
                "cardinality": "one",
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/3/attributes",
            data={"name": "Name", "data_type": "text"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/3/attributes",
            data={
                "name": "Rack",
                "data_type": "reference",
                "reference_entity_id": "2",
                "cardinality": "one",
            },
            follow_redirects=False,
        ).status_code
        == 303
    )
    # Records: site #1, rack #2 (site=1), server #3 (rack=2).
    assert (
        client.post("/entities/1/records", data={"name": "S1"}, follow_redirects=False).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/2/records", data={"name": "R1", "site": "1"}, follow_redirects=False
        ).status_code
        == 303
    )
    assert (
        client.post(
            "/entities/3/records", data={"name": "A", "rack": "2"}, follow_redirects=False
        ).status_code
        == 303
    )


def test_create_view_with_related_columns(client, login):
    _seed_with_references(client, login)
    resp = client.post(
        "/views",
        data={
            "name": "Servers",
            "entity_id": "3",
            "col": ["base:name", "rel:up:rack:2:first→name"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    html = client.get("/views/1").text
    assert "Rack › Name" in html
    assert "<th>Name</th>" in html
    assert "R1" in html


def test_create_view_malformed_column_values_ignored(client, login):
    _seed_with_references(client, login)
    resp = client.post(
        "/views",
        data={"name": "V", "entity_id": "3", "col": ["garbage", "rel:up:nope:2:first→name"]},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # No valid columns -> every attribute is shown.
    assert "<th>Name</th>" in client.get("/views/1").text
    assert "<th>Rack</th>" in client.get("/views/1").text


def test_edit_view_page_embeds_graph_and_replays_columns(client, login):
    _seed_with_references(client, login)
    client.post(
        "/views",
        data={"name": "V", "entity_id": "3", "col": ["rel:up:rack:2:first→name"]},
        follow_redirects=False,
    )
    html = client.get("/views/1/edit").text
    assert '"base"' in html
    assert '"entities"' in html
    # Stored column config is embedded for the JS replay.
    assert '"ref": "rack"' in html
    assert '"many": "first"' in html


def test_view_form_has_icon_picker(client, login):
    _seed_server(client, login)
    html = client.get("/views/new", params={"entity_id": 1}).text
    assert 'name="icon"' in html
    assert 'value="fa-bolt"' in html


def test_create_view_with_icon_shows_in_sidebar(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/views", data={"name": "V", "entity_id": "1", "icon": "fa-bolt"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert "fa-bolt" in client.get("/dashboard").text


def test_update_view_icon(client, login):
    _seed_server(client, login)
    client.post(
        "/views", data={"name": "V", "entity_id": "1", "icon": "fa-bolt"}, follow_redirects=False
    )
    client.post(
        "/views/1/edit",
        data={"name": "V", "entity_id": "1", "icon": "fa-cloud"},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    assert "fa-cloud" in html
    assert "fa-bolt" not in html


def test_invalid_view_icon_ignored(client, login):
    _seed_server(client, login)
    resp = client.post(
        "/views", data={"name": "V", "entity_id": "1", "icon": "bogus"}, follow_redirects=False
    )
    assert resp.status_code == 303
    html = client.get("/dashboard").text
    assert "bogus" not in html
    assert "fa-table" in html  # fallback icon in the menu


def test_sidebar_sections_and_custom_views(client, login):
    _seed_server(client, login)
    client.post("/views", data={"name": "Servers View", "entity_id": "1"}, follow_redirects=False)
    client.post(
        "/views",
        data={"name": "Cores View", "entity_id": "1", "icon": "fa-bolt"},
        follow_redirects=False,
    )
    html = client.get("/dashboard").text
    # Level-1: Dashboard link + two section titles.
    assert html.count("nav-section-title") == 2
    assert ">Configuration</span>" in html
    # Level-2 custom views in the sidebar, ordered by name.
    assert 'href="/views/1"' in html
    assert 'href="/views/2"' in html
    assert "Servers View" in html
    assert "fa-table" in html  # fallback icon for the view without one
    assert "fa-bolt" in html  # chosen icon
    # Configuration items: admin sees Users and Backup.
    assert 'aria-label="Users"' in html
    assert 'aria-label="Backup"' in html
    assert 'aria-label="Entities"' in html
