"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.main import create_app

ADMIN_PASSWORD = "admin-password-123"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        secret_key="test-secret-key",
        admin_username="admin",
        admin_password=ADMIN_PASSWORD,
        admin_display_name="Test Admin",
        session_ttl_days=7,
    )


@pytest.fixture
def engine(settings):
    """A SQLAlchemy engine with the schema created (no Alembic in tests)."""
    eng = build_engine(settings.database_url, settings.data_dir)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """A fresh ORM session bound to the test database."""
    factory = build_session_factory(engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(settings, engine):
    """A TestClient whose lifespan seeds the admin account."""
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(client):
    """Return a helper that logs in and stores the session cookie."""

    def _login(username: str = "admin", password: str = ADMIN_PASSWORD):
        return client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    return _login
