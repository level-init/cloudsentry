"""Append-only execution audit events for apply and rollback.

Revision ID: 0018_execution_audit
Revises: 0017_execution_applied_actions
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_execution_audit"
down_revision: str | None = "0017_execution_applied_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_events",
        sa.Column("event_id", sa.Integer(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(),
            sa.ForeignKey("execution_runs.execution_id"),
            nullable=False,
        ),
        sa.Column(
            "proposal_id",
            sa.String(),
            sa.ForeignKey("optimization_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_status", sa.String(), nullable=False),
        sa.Column("to_status", sa.String(), nullable=False),
    )
    op.execute(
        """
        CREATE FUNCTION execution_events_append_only()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'execution_events is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER execution_events_no_update
        BEFORE UPDATE ON execution_events
        FOR EACH ROW
        EXECUTE FUNCTION execution_events_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER execution_events_no_delete
        BEFORE DELETE ON execution_events
        FOR EACH ROW
        EXECUTE FUNCTION execution_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS execution_events_no_update ON execution_events")
    op.execute("DROP TRIGGER IF EXISTS execution_events_no_delete ON execution_events")
    op.execute("DROP FUNCTION IF EXISTS execution_events_append_only()")
    op.drop_table("execution_events")
