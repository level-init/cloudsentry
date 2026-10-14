"""SQLAlchemy tables for the inventory, proposal, and execution schemas."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ResourceRow(Base):
    __tablename__ = "resources"

    resource_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    team: Mapped[str] = mapped_column(String, nullable=False)
    business_criticality: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False)
    present: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sku: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_class: Mapped[str | None] = mapped_column(String, nullable=True)


class MetricRow(Base):
    __tablename__ = "metrics"

    metric_id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.resource_id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)


class MetricRollupRow(Base):
    __tablename__ = "metric_rollups"
    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "name",
            "day",
            name="uq_metric_rollups_resource_name_day",
        ),
    )

    rollup_id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.resource_id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    avg_value: Mapped[float] = mapped_column(Float, nullable=False)
    peak_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)


class CostRecordRow(Base):
    __tablename__ = "cost_records"
    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "period_start",
            name="uq_cost_records_resource_period",
        ),
    )

    cost_record_id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.resource_id"), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class DependencyRow(Base):
    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint(
            "source_resource_id",
            "target_resource_id",
            "relationship",
            name="uq_dependencies_edge",
        ),
    )

    dependency_id: Mapped[int] = mapped_column(primary_key=True)
    source_resource_id: Mapped[str] = mapped_column(
        ForeignKey("resources.resource_id"), nullable=False
    )
    target_resource_id: Mapped[str] = mapped_column(
        ForeignKey("resources.resource_id"), nullable=False
    )
    relationship: Mapped[str] = mapped_column(String, nullable=False)


class IncidentRow(Base):
    __tablename__ = "incidents"

    incident_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.resource_id"), nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)


class PolicyRow(Base):
    __tablename__ = "policies"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    effect: Mapped[str] = mapped_column(String, nullable=False)
    actions: Mapped[list] = mapped_column(JSONB, nullable=False)


class FindingRow(Base):
    __tablename__ = "findings"

    finding_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False)


class ProposalRow(Base):
    __tablename__ = "optimization_proposals"

    proposal_id: Mapped[str] = mapped_column(String, primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.finding_id"), nullable=False)
    resource_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    current_monthly_cost: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_monthly_cost: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_monthly_savings: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    business_criticality: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False)
    dependencies: Mapped[list] = mapped_column(JSONB, nullable=False)
    preconditions: Mapped[list] = mapped_column(JSONB, nullable=False)
    proposed_actions: Mapped[list] = mapped_column(JSONB, nullable=False)
    rollback_plan: Mapped[list] = mapped_column(JSONB, nullable=False)
    approval_status: Mapped[str] = mapped_column(String, nullable=False)
    execution_status: Mapped[str] = mapped_column(String, nullable=False)
    verification_status: Mapped[str] = mapped_column(String, nullable=False)
    realized_savings: Mapped[float | None] = mapped_column(Float, nullable=True)


class RiskAssessmentRow(Base):
    __tablename__ = "risk_assessments"

    risk_assessment_id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("optimization_proposals.proposal_id"), unique=True, nullable=False
    )
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_class: Mapped[str] = mapped_column(String, nullable=False)
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False)


class ExecutionRunRow(Base):
    __tablename__ = "execution_runs"

    execution_id: Mapped[str] = mapped_column(String, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("optimization_proposals.proposal_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    plan_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_plan: Mapped[list] = mapped_column(JSONB, nullable=False)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rolled_back_by: Mapped[str | None] = mapped_column(String, nullable=True)


class VerificationResultRow(Base):
    __tablename__ = "verification_results"

    verification_id: Mapped[str] = mapped_column(String, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("optimization_proposals.proposal_id"), nullable=False
    )
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("execution_runs.execution_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    predicted_monthly_savings: Mapped[float] = mapped_column(Float, nullable=False)
    realized_monthly_savings: Mapped[float] = mapped_column(Float, nullable=False)
    operational_impact: Mapped[str] = mapped_column(Text, nullable=False)


class RealizedSavingsRow(Base):
    __tablename__ = "realized_savings"

    savings_id: Mapped[str] = mapped_column(String, primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("optimization_proposals.proposal_id"), nullable=False
    )
    verification_id: Mapped[str] = mapped_column(
        ForeignKey("verification_results.verification_id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
