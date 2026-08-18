"""add attribute is_active

Revision ID: c9b8a7d6e5f4
Revises: a8f3d2c1b9e4
Create Date: 2026-08-16 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9b8a7d6e5f4"
down_revision: str | None = "a8f3d2c1b9e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.drop_column("is_active")
