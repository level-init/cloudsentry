"""Execution and verification schemas.

An approved OptimizationProposal becomes an ExecutionRun. After the change,
a VerificationResult compares predicted and realized savings and records
operational impact. RealizedSavings is the measured amount linked back to
the proposal. These models do not mutate the simulator.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.proposals import ExecutionStatus

_TERMINAL = frozenset(
    {
        ExecutionStatus.succeeded,
        ExecutionStatus.failed,
        ExecutionStatus.rolled_back,
    }
)

_ALLOWED = {
    ExecutionStatus.queued: frozenset(
        {
            ExecutionStatus.running,
            ExecutionStatus.failed,
        }
    ),
    ExecutionStatus.running: frozenset(
        {
            ExecutionStatus.succeeded,
            ExecutionStatus.failed,
            ExecutionStatus.rolled_back,
        }
    ),
    ExecutionStatus.succeeded: frozenset({ExecutionStatus.rolled_back}),
}


def require_run_transition(current: ExecutionStatus, target: ExecutionStatus) -> None:
    if current == target:
        raise ValueError(f"execution is already {current.value}")
    if target not in _ALLOWED.get(current, frozenset()):
        raise ValueError(f"cannot change execution from {current.value} to {target.value}")


def is_terminal(status: ExecutionStatus) -> bool:
    return status in _TERMINAL


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
