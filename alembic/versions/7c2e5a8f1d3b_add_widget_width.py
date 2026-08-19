"""add widget width

Revision ID: 7c2e5a8f1d3b
Revises: e5f8c3d7a1b2
Create Date: 2026-08-19 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c2e5a8f1d3b"
down_revision: str | None = "e5f8c3d7a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("dashboard_widgets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("width", sa.String(length=16), nullable=False, server_default="1/2")
        )


def downgrade() -> None:
    with op.batch_alter_table("dashboard_widgets", schema=None) as batch_op:
        batch_op.drop_column("width")
