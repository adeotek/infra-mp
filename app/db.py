"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def build_engine(database_url: str, data_dir: Path | None = None) -> Engine:
    """Create a SQLAlchemy engine, enabling SQLite pragmas when relevant."""
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)

    connect_args: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(database_url, connect_args=connect_args)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            # Bound write-lock wait (MCP + web share one DB) and a faster,
            # still-crash-safe synchronous mode. WAL + NORMAL only risks losing
            # the last transactions on power loss, never corruption.
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory with sane defaults."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session(request: Request) -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped database session."""
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
