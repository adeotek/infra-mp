"""add attribute hint

Revision ID: a8f3d2c1b9e4
Revises: f545bf0a233c
Create Date: 2026-08-16 18:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8f3d2c1b9e4"
down_revision: str | None = "f545bf0a233c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("hint", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("attributes", schema=None) as batch_op:
        batch_op.drop_column("hint")
