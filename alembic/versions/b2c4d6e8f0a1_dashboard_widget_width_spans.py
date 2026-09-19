"""dashboard widget widths to 12-column grid spans

Widget widths move from quarter/half/three-quarter/full tokens to 1-12 spans of
a 12-column grid. Existing rows are rewritten to the equivalent span so the
dashboard renders unchanged after the upgrade.

Revision ID: b2c4d6e8f0a1
Revises: f3e5d7c9a1b2
Create Date: 2026-09-19 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c4d6e8f0a1"
down_revision: str | None = "f3e5d7c9a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Legacy width token -> span of the 12-column grid.
LEGACY_TO_SPAN = {"1/4": "3", "1/2": "6", "3/4": "9", "full": "12"}


def upgrade() -> None:
    for legacy, span in LEGACY_TO_SPAN.items():
        op.execute(f"UPDATE dashboard_widgets SET width = '{span}' WHERE width = '{legacy}'")
    with op.batch_alter_table("dashboard_widgets", schema=None) as batch_op:
        batch_op.alter_column(
            "width",
            existing_type=sa.String(length=16),
            existing_nullable=False,
            server_default="6",
        )


def downgrade() -> None:
    for legacy, span in LEGACY_TO_SPAN.items():
        op.execute(f"UPDATE dashboard_widgets SET width = '{legacy}' WHERE width = '{span}'")
    with op.batch_alter_table("dashboard_widgets", schema=None) as batch_op:
        batch_op.alter_column(
            "width",
            existing_type=sa.String(length=16),
            existing_nullable=False,
            server_default="1/2",
        )
