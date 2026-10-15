"""Store success metrics on each optimization proposal.

Revision ID: 0010_proposal_success_metrics
Revises: 0009_policy_scope
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0010_proposal_success_metrics"
down_revision: str | None = "0009_policy_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "optimization_proposals",
        sa.Column("success_metrics", JSONB(), nullable=True),
    )
    op.execute(
        """
        UPDATE optimization_proposals
        SET success_metrics = COALESCE(
          (
            SELECT jsonb_agg(substring(item FROM 16))
            FROM jsonb_array_elements_text(evidence) AS item
            WHERE item LIKE 'success_metric %'
          ),
          '[]'::jsonb
        )
        """
    )
    op.execute(
        """
        UPDATE optimization_proposals
        SET success_metrics = '["monthly cost at or below the predicted monthly cost"]'::jsonb
        WHERE success_metrics IS NULL OR success_metrics = '[]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE optimization_proposals
        SET preconditions = '["the detector gate still holds"]'::jsonb
        WHERE preconditions IS NULL OR preconditions = '[]'::jsonb
        """
    )
    op.alter_column("optimization_proposals", "success_metrics", nullable=False)


def downgrade() -> None:
    op.drop_column("optimization_proposals", "success_metrics")
