"""Refuse updates and deletes on approval decisions.

Revision ID: 0013_approval_audit_append_only
Revises: 0012_approval_decision
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_approval_audit_append_only"
down_revision: str | None = "0012_approval_decision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION approval_decisions_append_only()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'approval_decisions is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER approval_decisions_no_update
        BEFORE UPDATE ON approval_decisions
        FOR EACH ROW
        EXECUTE FUNCTION approval_decisions_append_only()
        """
    )
    op.execute(
        """
        CREATE TRIGGER approval_decisions_no_delete
        BEFORE DELETE ON approval_decisions
        FOR EACH ROW
        EXECUTE FUNCTION approval_decisions_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS approval_decisions_no_update ON approval_decisions")
    op.execute("DROP TRIGGER IF EXISTS approval_decisions_no_delete ON approval_decisions")
    op.execute("DROP FUNCTION IF EXISTS approval_decisions_append_only()")
