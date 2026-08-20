"""add attribute is_key

Revision ID: b5e9d2f7a1c8
Revises: 7c2e5a8f1d3b
Create Date: 2026-08-19 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e9d2f7a1c8"
down_revision: str | None = "7c2e5a8f1d3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_key", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.drop_column("is_key")
