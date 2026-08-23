"""set records creator FKs to ON DELETE SET NULL

Deleting a user who authored records previously failed with an
IntegrityError because the created_by/updated_by foreign keys had no
ON DELETE action. SQLite cannot alter an FK action in place, so the
table is rebuilt with the new actions and the data copied over.

Revision ID: 9d1c4e7f2b3a
Revises: 7f7c07383cf9
Create Date: 2026-08-23 19:00:00
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d1c4e7f2b3a"
down_revision: str | None = "7f7c07383cf9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECORDS_COLUMNS = "id, entity_id, data, deleted_at, created_by, updated_by, created_at, updated_at"

_INDEXES = (
    "CREATE INDEX ix_records_entity_deleted ON records (entity_id, deleted_at)",
    "CREATE INDEX ix_records_entity_id ON records (entity_id)",
    "CREATE INDEX ix_records_deleted_at ON records (deleted_at)",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE records_new (
            id INTEGER NOT NULL PRIMARY KEY,
            entity_id INTEGER NOT NULL,
            data JSON NOT NULL,
            deleted_at DATETIME,
            created_by INTEGER,
            updated_by INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(entity_id) REFERENCES entities (id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL,
            FOREIGN KEY(updated_by) REFERENCES users (id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        f"INSERT INTO records_new ({_RECORDS_COLUMNS}) SELECT {_RECORDS_COLUMNS} FROM records"
    )
    op.execute("DROP TABLE records")
    op.execute("ALTER TABLE records_new RENAME TO records")
    for statement in _INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE records_old (
            id INTEGER NOT NULL PRIMARY KEY,
            entity_id INTEGER NOT NULL,
            data JSON NOT NULL,
            deleted_at DATETIME,
            created_by INTEGER,
            updated_by INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(entity_id) REFERENCES entities (id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users (id),
            FOREIGN KEY(updated_by) REFERENCES users (id)
        )
        """
    )
    op.execute(
        f"INSERT INTO records_old ({_RECORDS_COLUMNS}) SELECT {_RECORDS_COLUMNS} FROM records"
    )
    op.execute("DROP TABLE records")
    op.execute("ALTER TABLE records_old RENAME TO records")
    for statement in _INDEXES:
        op.execute(statement)
