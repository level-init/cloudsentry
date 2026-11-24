"""Store observation window and post-change snapshot on verification results.

Revision ID: 0020_verification_observation
Revises: 0019_execution_baseline
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_verification_observation"
down_revision: str | None = "0019_execution_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "verification_results",
        sa.Column("observation_window", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "verification_results",
        sa.Column("post_change", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("verification_results", "post_change")
    op.drop_column("verification_results", "observation_window")
