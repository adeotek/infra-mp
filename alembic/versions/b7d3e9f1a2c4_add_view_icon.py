"""add view icon

Revision ID: b7d3e9f1a2c4
Revises: c9b8a7d6e5f4
Create Date: 2026-08-18 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d3e9f1a2c4"
down_revision: str | None = "c9b8a7d6e5f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("views", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("icon", sa.String(length=64), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("views", schema=None) as batch_op:
        batch_op.drop_column("icon")
