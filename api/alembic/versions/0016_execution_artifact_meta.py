"""Record commit-like metadata for Terraform change artifacts.

Revision ID: 0016_execution_artifact_meta
Revises: 0015_execution_artifact_path
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_execution_artifact_meta"
down_revision: str | None = "0015_execution_artifact_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_runs",
        sa.Column("artifact_hash", sa.String(), nullable=True),
    )
    op.add_column(
        "execution_runs",
        sa.Column("artifact_created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_runs", "artifact_created_at")
    op.drop_column("execution_runs", "artifact_hash")
