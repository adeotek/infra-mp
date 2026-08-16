"""Edge-case tests: route 404s and admin seeding."""

from app.auth.seed import seed_admin
from app.config import Settings
from app.services.user_service import list_users


def test_edit_entity_404(client, login):
    login()
    assert client.get("/entities/9999/edit").status_code == 404


def test_update_entity_404(client, login):
    login()
    assert (
        client.post("/entities/9999/edit", data={"name": "x"}, follow_redirects=False).status_code
        == 404
    )


def test_delete_entity_404(client, login):
    login()
    assert client.post("/entities/9999/delete", follow_redirects=False).status_code == 404


def test_create_attribute_404(client, login):
    login()
    assert (
        client.post(
            "/entities/9999/attributes",
            data={"name": "x", "data_type": "text"},
            follow_redirects=False,
        ).status_code
        == 404
    )


def test_edit_attribute_page_404(client, login):
    login()
    assert client.get("/attributes/9999/edit").status_code == 404


def test_update_attribute_404(client, login):
    login()
    assert (
        client.post(
            "/attributes/9999/edit",
            data={"name": "x", "data_type": "text"},
            follow_redirects=False,
        ).status_code
        == 404
    )


def test_new_record_page_404(client, login):
    login()
    assert client.get("/entities/9999/records/new").status_code == 404


def test_create_record_404(client, login):
    login()
    assert (
        client.post(
            "/entities/9999/records", data={"name": "x"}, follow_redirects=False
        ).status_code
        == 404
    )


def test_update_view_404(client, login):
    login()
    assert (
        client.post(
            "/views/9999/edit", data={"name": "x", "entity_id": "1"}, follow_redirects=False
        ).status_code
        == 404
    )


def test_seed_admin_generates_password_and_is_idempotent(db_session):
    settings = Settings(admin_username="admin", admin_password="", admin_display_name="Admin")
    seed_admin(db_session, settings)  # no password set -> generates a random one and prints it
    seed_admin(db_session, settings)  # second call is a no-op (users already exist)
    assert len(list_users(db_session)) == 1
