"""Store the Terraform change artifact path on an execution run.

Revision ID: 0015_execution_artifact_path
Revises: 0014_notification
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_execution_artifact_path"
down_revision: str | None = "0014_notification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_runs",
        sa.Column("artifact_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_runs", "artifact_path")
