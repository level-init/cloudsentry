"""Record an in-app notification when a proposal is waiting for approval.

Revision ID: 0014_notification
Revises: 0013_approval_audit_append_only
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_notification"
down_revision: str | None = "0013_approval_audit_append_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.Integer(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(),
            sa.ForeignKey("optimization_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("team", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notifications")
