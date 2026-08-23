"""Health endpoint tests: liveness, readiness, MCP readiness."""

from starlette.testclient import TestClient

from app.db import Base, build_engine
from app.main import create_app


def test_healthz_liveness_is_open(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_is_open_with_working_database(client):
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_is_503_with_broken_database(settings):
    Base.metadata.create_all(build_engine(settings.database_url, settings.data_dir))
    app = create_app(settings)
    with TestClient(app) as c:
        assert c.get("/readyz").status_code == 200
        # Sabotage the database: close the app's pooled connections (open
        # handles would keep working on the unlinked file), then replace the
        # file with a directory so new connections fail to open.
        c.app.state.engine.dispose()
        db_file = settings.data_dir / "infra-mp.db"
        db_file.unlink()
        for suffix in ("-wal", "-shm"):
            leftover = settings.data_dir / f"infra-mp.db{suffix}"
            if leftover.exists():
                leftover.unlink()
        db_file.mkdir()
        resp = c.get("/readyz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unhealthy"
        db_file.rmdir()


def test_mcp_readyz_enabled(client):
    resp = client.get("/mcp/readyz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "mcp": "enabled"}


def test_mcp_readyz_disabled(settings, engine):
    disabled = settings.model_copy(update={"mcp_enabled": False})
    app = create_app(disabled)
    with TestClient(app) as c:
        resp = c.get("/mcp/readyz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "mcp": "disabled"}


def test_mcp_readyz_does_not_leak_into_the_mcp_subapp(client):
    # The route is served by the parent app, not the mounted /mcp sub-app:
    # a plain GET (no auth) must hit our handler, not the sub-app's 404/401.
    resp = client.get("/mcp/readyz")
    assert resp.status_code == 200
    assert "mcp" in resp.json()
