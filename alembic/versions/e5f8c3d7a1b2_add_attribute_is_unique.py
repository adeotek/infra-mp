"""add attribute is_unique

Revision ID: e5f8c3d7a1b2
Revises: b7d3e9f1a2c4
Create Date: 2026-08-18 20:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f8c3d7a1b2"
down_revision: str | None = "b7d3e9f1a2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_unique", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.drop_column("is_unique")
