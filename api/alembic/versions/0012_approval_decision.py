"""Record who approved, rejected, or cancelled a proposal, and why.

Revision ID: 0012_approval_decision
Revises: 0011_proposal_narrative
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_approval_decision"
down_revision: str | None = "0011_proposal_narrative"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_decisions",
        sa.Column("decision_id", sa.Integer(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(),
            sa.ForeignKey("optimization_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_status", sa.String(), nullable=False),
        sa.Column("to_status", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("approval_decisions")
