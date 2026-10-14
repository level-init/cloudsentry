"""Record each manual and scheduled detection batch.

Revision ID: 0008_detection_run
Revises: 0007_resource_storage_class
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_detection_run"
down_revision: str | None = "0007_resource_storage_class"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "detection_runs",
        sa.Column("run_id", sa.Integer(), primary_key=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detectors", sa.Integer(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("findings", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("detection_runs")
