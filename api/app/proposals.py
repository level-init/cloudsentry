"""Optimization proposal schemas.

A detector emits a Finding. Planning turns that into an OptimizationProposal
with a RiskAssessment. Approval, execution, and verification statuses are
placeholders until those workflows exist. Execution runs live in app.execution.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import BusinessCriticality


class RiskClass(StrEnum):
    safe_automation = "SAFE_AUTOMATION"
    approval_required = "APPROVAL_REQUIRED"
    engineering_review_required = "ENGINEERING_REVIEW_REQUIRED"
    rejected = "REJECTED"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class ExecutionStatus(StrEnum):
    not_started = "not_started"
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    rolled_back = "rolled_back"


class VerificationStatus(StrEnum):
    not_started = "not_started"
    in_progress = "in_progress"
    success = "success"
    partial = "partial"
    rollback = "rollback"
    inconclusive = "inconclusive"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(min_length=1)
    resource_ids: list[str] = Field(min_length=1)
    category: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_score: float = Field(ge=0, le=1)
    risk_class: RiskClass
    reasons: list[str] = Field(min_length=1)


class OptimizationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    finding_id: str = Field(min_length=1)
    resource_ids: list[str] = Field(min_length=1)
    category: str = Field(min_length=1)
    current_monthly_cost: float = Field(ge=0)
    predicted_monthly_cost: float = Field(ge=0)
    predicted_monthly_savings: float
    confidence: float = Field(ge=0, le=1)
    business_criticality: BusinessCriticality
    evidence: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    proposed_actions: list[str] = Field(min_length=1)
    rollback_plan: list[str] = Field(min_length=1)
    approval_status: ApprovalStatus = ApprovalStatus.pending
    execution_status: ExecutionStatus = ExecutionStatus.not_started
    verification_status: VerificationStatus = VerificationStatus.not_started
    realized_savings: float | None = None
    risk_assessment: RiskAssessment
