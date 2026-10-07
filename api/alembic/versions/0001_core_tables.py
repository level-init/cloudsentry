"""Create the core CloudSentry tables.

Revision ID: 0001_core_tables
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_core_tables"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

jsonb = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "resources",
        sa.Column("resource_id", sa.String(), primary_key=True),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("team", sa.String(), nullable=False),
        sa.Column("business_criticality", sa.String(), nullable=False),
        sa.Column("tags", jsonb, nullable=False),
    )
    op.create_table(
        "metrics",
        sa.Column("metric_id", sa.Integer(), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(),
            sa.ForeignKey("resources.resource_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
    )
    op.create_table(
        "cost_records",
        sa.Column("cost_record_id", sa.Integer(), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(),
            sa.ForeignKey("resources.resource_id"),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
    )
    op.create_table(
        "dependencies",
        sa.Column("dependency_id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_resource_id",
            sa.String(),
            sa.ForeignKey("resources.resource_id"),
            nullable=False,
        ),
        sa.Column(
            "target_resource_id",
            sa.String(),
            sa.ForeignKey("resources.resource_id"),
            nullable=False,
        ),
        sa.Column("relationship", sa.String(), nullable=False),
    )
    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.String(), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(),
            sa.ForeignKey("resources.resource_id"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
    )
    op.create_table(
        "policies",
        sa.Column("name", sa.String(), primary_key=True),
        sa.Column("effect", sa.String(), nullable=False),
        sa.Column("actions", jsonb, nullable=False),
    )
    op.create_table(
        "findings",
        sa.Column("finding_id", sa.String(), primary_key=True),
        sa.Column("resource_ids", jsonb, nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", jsonb, nullable=False),
    )
    op.create_table(
        "optimization_proposals",
        sa.Column("proposal_id", sa.String(), primary_key=True),
        sa.Column("finding_id", sa.String(), sa.ForeignKey("findings.finding_id"), nullable=False),
        sa.Column("resource_ids", jsonb, nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("current_monthly_cost", sa.Float(), nullable=False),
        sa.Column("predicted_monthly_cost", sa.Float(), nullable=False),
        sa.Column("predicted_monthly_savings", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("business_criticality", sa.String(), nullable=False),
        sa.Column("evidence", jsonb, nullable=False),
        sa.Column("dependencies", jsonb, nullable=False),
        sa.Column("preconditions", jsonb, nullable=False),
        sa.Column("proposed_actions", jsonb, nullable=False),
        sa.Column("rollback_plan", jsonb, nullable=False),
        sa.Column("approval_status", sa.String(), nullable=False),
        sa.Column("execution_status", sa.String(), nullable=False),
        sa.Column("verification_status", sa.String(), nullable=False),
        sa.Column("realized_savings", sa.Float(), nullable=True),
    )
    op.create_table(
        "risk_assessments",
        sa.Column("risk_assessment_id", sa.Integer(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(),
            sa.ForeignKey("optimization_proposals.proposal_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("risk_class", sa.String(), nullable=False),
        sa.Column("reasons", jsonb, nullable=False),
    )
    op.create_table(
        "execution_runs",
        sa.Column("execution_id", sa.String(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(),
            sa.ForeignKey("optimization_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("plan_snapshot", jsonb, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_plan", jsonb, nullable=False),
        sa.Column("rollback_reason", sa.Text(), nullable=True),
        sa.Column("rolled_back_by", sa.String(), nullable=True),
    )
    op.create_table(
        "verification_results",
        sa.Column("verification_id", sa.String(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(),
            sa.ForeignKey("optimization_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            sa.String(),
            sa.ForeignKey("execution_runs.execution_id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("predicted_monthly_savings", sa.Float(), nullable=False),
        sa.Column("realized_monthly_savings", sa.Float(), nullable=False),
        sa.Column("operational_impact", sa.Text(), nullable=False),
    )
    op.create_table(
        "realized_savings",
        sa.Column("savings_id", sa.String(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(),
            sa.ForeignKey("optimization_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column(
            "verification_id",
            sa.String(),
            sa.ForeignKey("verification_results.verification_id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("realized_savings")
    op.drop_table("verification_results")
    op.drop_table("execution_runs")
    op.drop_table("risk_assessments")
    op.drop_table("optimization_proposals")
    op.drop_table("findings")
    op.drop_table("policies")
    op.drop_table("incidents")
    op.drop_table("dependencies")
    op.drop_table("cost_records")
    op.drop_table("metrics")
    op.drop_table("resources")
