"""Store one daily avg/peak rollup per metric.

Revision ID: 0002_metric_rollups
Revises: 0001_core_tables
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_metric_rollups"
down_revision: str | None = "0001_core_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metric_rollups",
        sa.Column("rollup_id", sa.Integer(), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(),
            sa.ForeignKey("resources.resource_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("avg_value", sa.Float(), nullable=False),
        sa.Column("peak_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "resource_id",
            "name",
            "day",
            name="uq_metric_rollups_resource_name_day",
        ),
    )


def downgrade() -> None:
    op.drop_table("metric_rollups")
