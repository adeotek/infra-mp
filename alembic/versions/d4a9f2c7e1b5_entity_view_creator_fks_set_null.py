"""set entity and view creator FKs to ON DELETE SET NULL

Deleting a user who created entities or views previously failed with an
IntegrityError because the created_by foreign keys on both tables had no
ON DELETE action (records got theirs in 9d1c4e7f2b3a). SQLite cannot alter
an FK action in place, so each table is rebuilt with the new action and
the data copied over.

Revision ID: d4a9f2c7e1b5
Revises: b2c4d6e8f0a1
Create Date: 2026-09-19 20:00:00
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4a9f2c7e1b5"
down_revision: str | None = "b2c4d6e8f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITIES_COLUMNS = "id, name, slug, description, icon, created_by, created_at, updated_at"
_VIEWS_COLUMNS = "id, name, slug, entity_id, config, created_by, created_at, updated_at, icon"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entities_new (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            slug VARCHAR(128) NOT NULL,
            description VARCHAR(500) NOT NULL,
            icon VARCHAR(64) NOT NULL,
            created_by INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uq_entities_name UNIQUE (name),
            FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        f"INSERT INTO entities_new ({_ENTITIES_COLUMNS}) SELECT {_ENTITIES_COLUMNS} FROM entities"
    )
    op.execute("DROP TABLE entities")
    op.execute("ALTER TABLE entities_new RENAME TO entities")
    op.execute("CREATE UNIQUE INDEX ix_entities_slug ON entities (slug)")

    op.execute(
        """
        CREATE TABLE views_new (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            slug VARCHAR(128) NOT NULL,
            entity_id INTEGER NOT NULL,
            config JSON NOT NULL,
            created_by INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            icon VARCHAR(64) NOT NULL,
            CONSTRAINT uq_view_entity_slug UNIQUE (entity_id, slug),
            FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
            FOREIGN KEY(entity_id) REFERENCES entities (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(f"INSERT INTO views_new ({_VIEWS_COLUMNS}) SELECT {_VIEWS_COLUMNS} FROM views")
    op.execute("DROP TABLE views")
    op.execute("ALTER TABLE views_new RENAME TO views")
    op.execute("CREATE INDEX ix_views_entity_id ON views (entity_id)")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE entities_old (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            slug VARCHAR(128) NOT NULL,
            description VARCHAR(500) NOT NULL,
            icon VARCHAR(64) NOT NULL,
            created_by INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uq_entities_name UNIQUE (name),
            FOREIGN KEY(created_by) REFERENCES users (id)
        )
        """
    )
    op.execute(
        f"INSERT INTO entities_old ({_ENTITIES_COLUMNS}) SELECT {_ENTITIES_COLUMNS} FROM entities"
    )
    op.execute("DROP TABLE entities")
    op.execute("ALTER TABLE entities_old RENAME TO entities")
    op.execute("CREATE UNIQUE INDEX ix_entities_slug ON entities (slug)")

    op.execute(
        """
        CREATE TABLE views_old (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            slug VARCHAR(128) NOT NULL,
            entity_id INTEGER NOT NULL,
            config JSON NOT NULL,
            created_by INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            icon VARCHAR(64) NOT NULL,
            CONSTRAINT uq_view_entity_slug UNIQUE (entity_id, slug),
            FOREIGN KEY(created_by) REFERENCES users (id),
            FOREIGN KEY(entity_id) REFERENCES entities (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(f"INSERT INTO views_old ({_VIEWS_COLUMNS}) SELECT {_VIEWS_COLUMNS} FROM views")
    op.execute("DROP TABLE views")
    op.execute("ALTER TABLE views_old RENAME TO views")
    op.execute("CREATE INDEX ix_views_entity_id ON views (entity_id)")
