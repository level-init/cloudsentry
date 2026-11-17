"""Store simulator action ids applied during an execution run.

Revision ID: 0017_execution_applied_actions
Revises: 0016_execution_artifact_meta
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_execution_applied_actions"
down_revision: str | None = "0016_execution_artifact_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_runs",
        sa.Column(
            "applied_action_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("execution_runs", "applied_action_ids")
