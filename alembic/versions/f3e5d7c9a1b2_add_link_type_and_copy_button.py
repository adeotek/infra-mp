"""Add link data type and with_copy_button flag.

Revision ID: f3e5d7c9a1b2
Revises: 9d1c4e7f2b3a
Create Date: 2026-09-12

- ``attributes.with_copy_button`` boolean flag (renders a copy-to-clipboard
  button next to the attribute's inputs/cells).
The ``link`` data type needs no schema change: data types are strings stored
in ``attributes.data_type``.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "f3e5d7c9a1b2"
down_revision: str | None = "9d1c4e7f2b3a"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "with_copy_button",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.drop_column("with_copy_button")
