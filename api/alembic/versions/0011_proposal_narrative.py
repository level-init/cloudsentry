"""Store an optional narrative on each optimization proposal.

Revision ID: 0011_proposal_narrative
Revises: 0010_proposal_success_metrics
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_proposal_narrative"
down_revision: str | None = "0010_proposal_success_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("optimization_proposals", sa.Column("narrative", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("optimization_proposals", "narrative")
