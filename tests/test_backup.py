"""HTTP tests for the admin backup/restore feature."""

import io
import os
import sqlite3
import tempfile
import zipfile


def _zip_with_db(db_bytes: bytes, name: str = "infra-mp.db") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, db_bytes)
    return buf.getvalue()


def _entity_names_from_bytes(db_bytes: bytes) -> list[str]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        handle.write(db_bytes)
        path = handle.name
    try:
        conn = sqlite3.connect(path)
        try:
            return [row[0] for row in conn.execute("SELECT name FROM entities ORDER BY name")]
        finally:
            conn.close()
    finally:
        os.unlink(path)


def test_backup_page_requires_auth(client):
    resp = client.get("/settings/backup", follow_redirects=False)
    assert resp.status_code in (302, 303, 307)


def test_backup_page(client, login):
    login()
    assert client.get("/settings/backup").status_code == 200


def test_backup_download_returns_zip(client, login):
    login()
    client.post("/entities", data={"name": "Server"}, follow_redirects=False)
    resp = client.get("/settings/backup/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "infra-mp.db" in zf.namelist()
        db_bytes = zf.read("infra-mp.db")
    # The snapshot is a valid SQLite DB and contains the created entity.
    assert db_bytes[:16] == b"SQLite format 3\x00"
    assert _entity_names_from_bytes(db_bytes) == ["Server"]


def test_restore_replaces_database(client, login):
    login()
    client.post("/entities", data={"name": "Alpha"}, follow_redirects=False)
    backup = client.get("/settings/backup/download").content

    client.post("/entities", data={"name": "Beta"}, follow_redirects=False)

    resp = client.post(
        "/settings/backup/restore",
        files={"file": ("backup.zip", backup, "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Session is cleared by the restore; log in again and verify the DB state.
    login()
    html = client.get("/entities").text
    assert "Alpha" in html
    assert "Beta" not in html


def test_restore_rejects_invalid_archive(client, login):
    login()
    resp = client.post(
        "/settings/backup/restore",
        files={"file": ("notzip.zip", b"this is not a zip", "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash_type=error" in resp.headers["location"]


def test_restore_rejects_missing_db(client, login):
    login()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.txt", "hello")
    resp = client.post(
        "/settings/backup/restore",
        files={"file": ("backup.zip", buf.getvalue(), "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash_type=error" in resp.headers["location"]


def test_restore_rejects_invalid_sqlite(client, login):
    login()
    resp = client.post(
        "/settings/backup/restore",
        files={"file": ("backup.zip", _zip_with_db(b"not a database"), "application/zip")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "flash_type=error" in resp.headers["location"]
