"""Execution and verification schemas.

An approved OptimizationProposal becomes an ExecutionRun. After the change,
a VerificationResult compares predicted and realized savings and records
operational impact. RealizedSavings is the measured amount linked back to
the proposal. These models do not perform execution.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.proposals import ExecutionStatus


class VerificationOutcome(StrEnum):
    success = "success"
    partial = "partial"
    rollback = "rollback"
    inconclusive = "inconclusive"


class ExecutionRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    status: ExecutionStatus
    actor: str = Field(min_length=1)
    plan_snapshot: list[str] = Field(min_length=1)
    started_at: datetime
    finished_at: datetime | None = None
    rollback_plan: list[str] = Field(min_length=1)
    rollback_reason: str | None = None
    rolled_back_by: str | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    status: VerificationOutcome
    predicted_monthly_savings: float
    realized_monthly_savings: float
    operational_impact: str = Field(min_length=1)


class RealizedSavings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    savings_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    verification_id: str = Field(min_length=1)
    amount: float
    period_start: datetime
    period_end: datetime
    currency: str = Field(default="USD", min_length=3, max_length=3)
