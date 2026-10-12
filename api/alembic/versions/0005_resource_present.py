"""Mark resources the simulator no longer returns.

Revision ID: 0005_resource_present
Revises: 0004_dependency_edge
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_resource_present"
down_revision: str | None = "0004_dependency_edge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resources",
        sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("resources", "present")
