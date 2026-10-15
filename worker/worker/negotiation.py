"""Cost versus reliability compromise.

Phase 7 can replace the no-op. The request carries the cost position, the
reliability position, and the plan. The result carries the plan to store.
`changed` is false when that plan is the original one. The no-op always
returns the original plan.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CostPosition:
    current_monthly_cost: float
    predicted_monthly_cost: float
    predicted_monthly_savings: float


@dataclass(frozen=True)
class ReliabilityPosition:
    risk_score: float
    risk_class: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    action: str
    rollback: str
    preconditions: tuple[str, ...]
    success_metrics: tuple[str, ...]


@dataclass(frozen=True)
class CompromiseRequest:
    resource_id: str
    category: str
    cost: CostPosition
    reliability: ReliabilityPosition
    plan: Plan


@dataclass(frozen=True)
class CompromiseResult:
    plan: Plan
    changed: bool


class Negotiator(Protocol):
    def compromise(self, request: CompromiseRequest) -> CompromiseResult:
        """Return the plan to store for this cost and reliability position."""


class NoOpNegotiator:
    def compromise(self, request: CompromiseRequest) -> CompromiseResult:
        return CompromiseResult(plan=request.plan, changed=False)


def apply_negotiation(
    request: CompromiseRequest,
    *,
    enabled: bool,
    negotiator: Negotiator | None = None,
) -> CompromiseResult:
    if not enabled:
        return CompromiseResult(plan=request.plan, changed=False)
    chosen = NoOpNegotiator() if negotiator is None else negotiator
    return chosen.compromise(request)
