"""Keep one cost row per resource and period start.

Revision ID: 0003_cost_record_period
Revises: 0002_metric_rollups
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_cost_record_period"
down_revision: str | None = "0002_metric_rollups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_cost_records_resource_period",
        "cost_records",
        ["resource_id", "period_start"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_cost_records_resource_period", "cost_records", type_="unique")
