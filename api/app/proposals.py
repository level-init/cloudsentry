"""Optimization proposal schemas.

A detector emits a Finding. Planning turns that into an OptimizationProposal
with a RiskAssessment. Every proposal carries preconditions, execution steps,
a rollback, and success metrics. Blank or empty plan lists are rejected.
Approval can move from pending to approved, rejected, or cancelled.
Execution and verification statuses are placeholders until those workflows
exist. Execution runs live in app.execution.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

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
    preconditions: list[str] = Field(min_length=1)
    proposed_actions: list[str] = Field(min_length=1)
    rollback_plan: list[str] = Field(min_length=1)
    success_metrics: list[str] = Field(min_length=1)
    approval_status: ApprovalStatus = ApprovalStatus.pending
    execution_status: ExecutionStatus = ExecutionStatus.not_started
    verification_status: VerificationStatus = VerificationStatus.not_started
    realized_savings: float | None = None
    narrative: str | None = None
    risk_assessment: RiskAssessment

    @model_validator(mode="before")
    @classmethod
    def _accept_plan_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        _copy_alias(data, "execution_steps", "proposed_actions")
        _copy_alias(data, "rollback", "rollback_plan")
        return data

    @field_validator(
        "preconditions",
        "proposed_actions",
        "rollback_plan",
        "success_metrics",
    )
    @classmethod
    def _reject_blank_plan_lines(cls, lines: list[str]) -> list[str]:
        if any(not line.strip() for line in lines):
            raise ValueError("plan lines must be non-blank")
        return lines

    @field_validator("narrative")
    @classmethod
    def _reject_blank_narrative(cls, narrative: str | None) -> str | None:
        if narrative is not None and not narrative.strip():
            raise ValueError("narrative must be non-blank")
        return narrative

    @computed_field
    @property
    def execution_steps(self) -> list[str]:
        return self.proposed_actions

    @computed_field
    @property
    def rollback(self) -> list[str]:
        return self.rollback_plan


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    decided_at: datetime
    from_status: ApprovalStatus
    to_status: ApprovalStatus


class ProposalList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OptimizationProposal]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


def _copy_alias(data: dict[str, Any], alias: str, field: str) -> None:
    if alias not in data:
        return
    if field in data and data[field] != data[alias]:
        raise ValueError(f"{alias} and {field} must match")
    data.setdefault(field, data.pop(alias))
    data.pop(alias, None)
