"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.main import create_app
from app.models.enums import DataType
from app.schemas.attribute import AttributeCreate
from app.schemas.entity import EntityCreate
from app.services.record_service import create_record
from app.services.schema_service import (
    add_attribute,
    create_entity,
    get_entity_with_attributes,
    list_entities,
)

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
def admin_password():
    """The seeded admin password (matches ``settings.admin_password``)."""
    return ADMIN_PASSWORD


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


@pytest.fixture
def ref_graph(db_session):
    """Site <- Rack <- Server -> NICs (many); records across all entities."""
    site = create_entity(db_session, EntityCreate(name="Site"))
    add_attribute(db_session, site, AttributeCreate(name="Name", data_type=DataType.TEXT))

    rack = create_entity(db_session, EntityCreate(name="Rack"))
    add_attribute(db_session, rack, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(
        db_session,
        rack,
        AttributeCreate(
            name="Site",
            data_type=DataType.REFERENCE,
            reference_entity_id=site.id,
            cardinality="one",
        ),
    )

    nic = create_entity(db_session, EntityCreate(name="NIC"))
    add_attribute(db_session, nic, AttributeCreate(name="IP", data_type=DataType.TEXT))

    server = create_entity(db_session, EntityCreate(name="Server"))
    add_attribute(db_session, server, AttributeCreate(name="Name", data_type=DataType.TEXT))
    add_attribute(
        db_session,
        server,
        AttributeCreate(
            name="Rack",
            data_type=DataType.REFERENCE,
            reference_entity_id=rack.id,
            cardinality="one",
        ),
    )
    add_attribute(
        db_session,
        server,
        AttributeCreate(
            name="NICs",
            data_type=DataType.REFERENCE,
            reference_entity_id=nic.id,
            cardinality="many",
        ),
    )

    def _reload(entity):
        loaded = get_entity_with_attributes(db_session, entity.id)
        assert loaded is not None
        return loaded

    site = _reload(site)
    rack = _reload(rack)
    nic = _reload(nic)
    server = _reload(server)

    s1 = create_record(db_session, site, site.attributes, {"name": "S1"})
    s2 = create_record(db_session, site, site.attributes, {"name": "S2"})
    r1 = create_record(db_session, rack, rack.attributes, {"name": "R1", "site": s1.id})
    r2 = create_record(db_session, rack, rack.attributes, {"name": "R2", "site": s2.id})
    n1 = create_record(db_session, nic, nic.attributes, {"ip": "10.0.0.1"})
    n2 = create_record(db_session, nic, nic.attributes, {"ip": "10.0.0.2"})
    n3 = create_record(db_session, nic, nic.attributes, {"ip": "10.0.0.3"})
    create_record(
        db_session,
        server,
        server.attributes,
        {
            "name": "A",
            "rack": r1.id,
            "nics": [n1.id, n2.id],
        },
    )
    create_record(
        db_session,
        server,
        server.attributes,
        {
            "name": "B",
            "rack": r2.id,
            "nics": [n3.id],
        },
    )
    create_record(db_session, server, server.attributes, {"name": "C"})
    create_record(db_session, server, server.attributes, {"name": "D", "nics": [n1.id, n2.id]})
    return {
        "site": site,
        "rack": rack,
        "nic": nic,
        "server": server,
        "entities": list_entities(db_session),
    }
