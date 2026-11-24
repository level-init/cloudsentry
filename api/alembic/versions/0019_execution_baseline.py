"""Store the pre-change cost and ops baseline on an execution run.

Revision ID: 0019_execution_baseline
Revises: 0018_execution_audit
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_execution_baseline"
down_revision: str | None = "0018_execution_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_runs",
        sa.Column("baseline", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_runs", "baseline")
