from app.proposals import RiskAssessment
from app.schemas import Resource
from worker.negotiation import (
    CompromiseRequest,
    CompromiseResult,
    CostPosition,
    NoOpNegotiator,
    Plan,
    ReliabilityPosition,
    apply_negotiation,
)
from worker.proposals import _Plan, _with_negotiation
from worker.savings import Savings


def test_noop_returns_the_original_plan() -> None:
    request = _request()

    result = NoOpNegotiator().compromise(request)

    assert result.plan is request.plan
    assert result.changed is False


def test_disabled_negotiation_keeps_the_original_plan() -> None:
    request = _request()

    result = apply_negotiation(request, enabled=False, negotiator=_Changer())

    assert result.plan is request.plan
    assert result.changed is False


def test_planner_skips_negotiation_when_the_flag_is_off() -> None:
    plan = _planner_plan()

    assert _with_negotiation(plan, _resource(), _risk(), "idle_compute", enabled=False) is plan


def test_planner_noop_returns_the_same_plan() -> None:
    plan = _planner_plan()

    negotiated = _with_negotiation(plan, _resource(), _risk(), "idle_compute", enabled=True)

    assert negotiated is plan


class _Changer:
    def compromise(self, request: CompromiseRequest) -> CompromiseResult:
        changed = Plan(
            action="stop harder",
            rollback=request.plan.rollback,
            preconditions=request.plan.preconditions,
            success_metrics=request.plan.success_metrics,
        )
        return CompromiseResult(plan=changed, changed=True)


def _request() -> CompromiseRequest:
    plan = Plan(
        action="stop i-neg",
        rollback="start i-neg",
        preconditions=("compute is present",),
        success_metrics=("monthly cost at or below 0.00",),
    )
    return CompromiseRequest(
        resource_id="i-neg",
        category="idle_compute",
        cost=CostPosition(
            current_monthly_cost=30.37,
            predicted_monthly_cost=0.0,
            predicted_monthly_savings=30.37,
        ),
        reliability=ReliabilityPosition(
            risk_score=0.05,
            risk_class="SAFE_AUTOMATION",
            reasons=("development resource",),
        ),
        plan=plan,
    )


def _planner_plan() -> _Plan:
    return _Plan(
        action="stop i-neg",
        rollback="start i-neg",
        savings=Savings(3037, 0),
        preconditions=["compute is present"],
        success_metric="monthly cost at or below 0.00",
    )


def _resource() -> Resource:
    return Resource(
        resource_id="i-neg",
        resource_type="compute",
        account_id="111111111111",
        environment="development",
        owner="payments-team",
        team="payments",
        business_criticality="low",
    )


def _risk() -> RiskAssessment:
    return RiskAssessment(
        risk_score=0.05,
        risk_class="SAFE_AUTOMATION",
        reasons=["development resource"],
    )
