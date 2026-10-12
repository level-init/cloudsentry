"""Keep one row per dependency edge.

Revision ID: 0004_dependency_edge
Revises: 0003_cost_record_period
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_dependency_edge"
down_revision: str | None = "0003_cost_record_period"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_dependencies_edge",
        "dependencies",
        ["source_resource_id", "target_resource_id", "relationship"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_dependencies_edge", "dependencies", type_="unique")
