"""Turn stored findings into Optimization Proposals.

Each MVP category has a fixed action and rollback. Costs stay in cents until
the proposal stores dollars. The compute rates and the 40/168 weekday schedule
match simulator/simulator/billing.py. Success metrics are stored on the
proposal and copied into evidence.

A second build skips a pending proposal with the same
resource ids and the same action. A rejected proposal does not block a new one.
"""

import logging
from dataclasses import dataclass, replace

from sqlalchemy.orm import Session

from app.db import create_session
from app.proposals import ApprovalStatus, OptimizationProposal, RiskClass
from app.repositories import (
    CostRecordRepository,
    DependencyRepository,
    FindingRepository,
    ProposalRepository,
    ResourceRepository,
)
from app.schemas import Resource
from worker.config import get_settings
from worker.negotiation import (
    CompromiseRequest,
    CostPosition,
    Negotiator,
    Plan,
    ReliabilityPosition,
    apply_negotiation,
)
from worker.risk import assess
from worker.savings import (
    Savings,
    delete_savings,
    lifecycle_savings,
    resize_savings,
    schedule_savings,
    stop_savings,
)
from worker.slack import notify_slack

_CONFIDENCE = 0.8


@dataclass(frozen=True)
class _Plan:
    action: str
    rollback: str
    savings: Savings
    preconditions: list[str]
    success_metric: str


@dataclass(frozen=True)
class ProposeResult:
    created: list[OptimizationProposal]
    skipped: list[OptimizationProposal]


def save_proposals() -> ProposeResult:
    session = create_session()
    try:
        result = propose(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    logging.info("propose created=%s skipped=%s", len(result.created), len(result.skipped))
    return result


def propose(session: Session) -> ProposeResult:
    findings = FindingRepository(session).list()
    resources = ResourceRepository(session)
    costs = CostRecordRepository(session)
    proposals = ProposalRepository(session)
    created: list[OptimizationProposal] = []
    skipped: list[OptimizationProposal] = []
    for finding in findings:
        builder = _BUILDERS.get(finding.category)
        if builder is None or len(finding.resource_ids) != 1:
            continue
        resource_id = finding.resource_ids[0]
        resource = resources.get(resource_id)
        if resource is None or not resource.present:
            continue
        current = _current_cents(costs, resource_id, finding.evidence)
        plan = builder(resource, finding.evidence, current)
        if plan is None:
            continue
        if finding.category == "rightsizing_veto":
            existing = proposals.find_with_action(finding.resource_ids, plan.action)
        else:
            existing = proposals.find_open(finding.resource_ids, plan.action)
        if existing is not None:
            skipped.append(existing)
            continue
        proposal = _proposal(session, finding, resource, plan)
        proposals.create(proposal)
        notify_slack(
            proposal.proposal_id,
            enabled=(
                get_settings().slack_webhook_enabled
                and proposal.approval_status == ApprovalStatus.pending
            ),
        )
        created.append(proposal)
    return ProposeResult(created=created, skipped=skipped)


def _proposal(session: Session, finding, resource: Resource, plan: _Plan) -> OptimizationProposal:
    edges = DependencyRepository(session).dependencies_of(resource.resource_id)
    evidence = list(finding.evidence)
    evidence.append(f"success_metric {plan.success_metric}")
    risk = assess(session, resource.resource_id)
    approval = ApprovalStatus.pending
    if finding.category == "rightsizing_veto":
        approval = ApprovalStatus.rejected
        risk = risk.model_copy(
            update={
                "risk_class": RiskClass.rejected,
                "reasons": [*risk.reasons, _veto_reason(finding.evidence)],
            }
        )
    plan = _with_negotiation(
        plan,
        resource,
        risk,
        finding.category,
        enabled=get_settings().negotiation_enabled,
    )
    return OptimizationProposal(
        proposal_id=_proposal_id(session, finding.finding_id),
        finding_id=finding.finding_id,
        resource_ids=list(finding.resource_ids),
        category=finding.category,
        current_monthly_cost=_dollars(plan.savings.current_cents),
        predicted_monthly_cost=_dollars(plan.savings.predicted_cents),
        predicted_monthly_savings=_dollars(plan.savings.savings_cents),
        confidence=_CONFIDENCE,
        business_criticality=resource.business_criticality,
        evidence=evidence,
        dependencies=[f"{edge.relationship} {edge.target_resource_id}" for edge in edges],
        preconditions=plan.preconditions,
        proposed_actions=[plan.action],
        rollback_plan=[plan.rollback],
        success_metrics=[plan.success_metric],
        approval_status=approval,
        risk_assessment=risk,
    )


def _with_negotiation(
    plan: _Plan,
    resource: Resource,
    risk,
    category: str,
    *,
    enabled: bool,
    negotiator: Negotiator | None = None,
) -> _Plan:
    if not enabled:
        return plan
    current = _dollars(plan.savings.current_cents)
    predicted = _dollars(plan.savings.predicted_cents)
    request = CompromiseRequest(
        resource_id=resource.resource_id,
        category=category,
        cost=CostPosition(
            current_monthly_cost=current,
            predicted_monthly_cost=predicted,
            predicted_monthly_savings=_dollars(plan.savings.savings_cents),
        ),
        reliability=ReliabilityPosition(
            risk_score=risk.risk_score,
            risk_class=risk.risk_class.value,
            reasons=tuple(risk.reasons),
        ),
        plan=Plan(
            action=plan.action,
            rollback=plan.rollback,
            preconditions=tuple(plan.preconditions),
            success_metrics=(plan.success_metric,),
        ),
    )
    result = apply_negotiation(request, enabled=True, negotiator=negotiator)
    if not result.changed:
        return plan
    success_metric = plan.success_metric
    if result.plan.success_metrics:
        success_metric = result.plan.success_metrics[0]
    return replace(
        plan,
        action=result.plan.action,
        rollback=result.plan.rollback,
        preconditions=list(result.plan.preconditions),
        success_metric=success_metric,
    )


def _proposal_id(session: Session, finding_id: str) -> str:
    repository = ProposalRepository(session)
    base = f"proposal-{finding_id}"
    if repository.get(base) is None:
        return base
    suffix = 2
    while repository.get(f"{base}-{suffix}") is not None:
        suffix += 1
    return f"{base}-{suffix}"


def _idle(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    if current is None:
        return None
    return _Plan(
        action=f"stop {resource.resource_id}",
        rollback=f"start {resource.resource_id}",
        savings=stop_savings(current),
        preconditions=[
            "compute is present",
            "cpu and request averages and peaks stay under the idle caps",
        ],
        success_metric="monthly cost at or below 0.00",
    )


def _rightsizing(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    recommended = _value(evidence, "recommended_sku")
    current_sku = _value(evidence, "current_sku")
    priced = None
    if current is not None and recommended is not None:
        priced = resize_savings(current, recommended)
    if priced is None or not current_sku:
        return None
    return _Plan(
        action=f"resize {resource.resource_id} to {recommended}",
        rollback=f"resize {resource.resource_id} to {current_sku}",
        savings=priced,
        preconditions=[
            f"recommended sku is {recommended}",
            "projected peak stays inside the rightsizing headroom",
        ],
        success_metric=f"monthly cost at or below {_dollars(priced.predicted_cents):.2f}",
    )


def _scheduling(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    if current is None:
        return None
    priced = schedule_savings(current)
    return _Plan(
        action=f"schedule {resource.resource_id} weekdays-09-17",
        rollback=f"schedule {resource.resource_id} always_on",
        savings=priced,
        preconditions=[
            "environment is development or staging",
            "weekend and weekday cpu averages stay at or above 20",
        ],
        success_metric=f"monthly cost at or below {_dollars(priced.predicted_cents):.2f}",
    )


def _unattached(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    if current is None:
        return None
    if resource.resource_type == "disk":
        rollback = f"recreate {resource.resource_id} from a snapshot or backup"
    else:
        rollback = (
            f"recreate {resource.resource_id} from its source disk while that disk still exists"
        )
    return _Plan(
        action=f"delete {resource.resource_id}",
        rollback=rollback,
        savings=delete_savings(current),
        preconditions=[
            "nothing depends on the resource",
            "cost history meets the storage age gate",
        ],
        success_metric="monthly cost at or below 0.00",
    )


def _lifecycle(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    action = _value(evidence, "action")
    if current is None or action is None:
        return None
    priced = lifecycle_savings(current, action)
    if priced is None:
        return None
    if action == "transition-to-infrequent-access":
        return _Plan(
            action=f"transition {resource.resource_id} to infrequent_access",
            rollback=f"transition {resource.resource_id} to standard",
            savings=priced,
            preconditions=[
                "storage class is standard",
                "monthly cost meets the lifecycle floor",
            ],
            success_metric=f"monthly cost at or below {_dollars(priced.predicted_cents):.2f}",
        )
    return _Plan(
        action=f"expire {resource.resource_id}",
        rollback=(
            f"recreate {resource.resource_id} from its source disk while that disk still exists"
        ),
        savings=priced,
        preconditions=[
            "snapshot is outside production",
            "nothing depends on the snapshot",
            "cost history meets the retention age",
        ],
        success_metric="monthly cost at or below 0.00",
    )


def _veto(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    rejected = _value(evidence, "rejected_sku")
    current_sku = _value(evidence, "current_sku")
    if not rejected or not current_sku:
        return None
    cents = 0 if current is None else current
    return _Plan(
        action=f"reject resize of {resource.resource_id} to {rejected}",
        rollback=f"keep {resource.resource_id} at {current_sku}",
        savings=Savings(cents, cents),
        preconditions=["projected peak on the next sku stays over the headroom cap"],
        success_metric=f"sku stays {current_sku}",
    )


def _veto_reason(evidence: list[str]) -> str:
    rejected = _value(evidence, "rejected_sku") or "the next sku"
    projected = _value(evidence, "projected_peak") or "over the cap"
    two_step = _value(evidence, "two_step_projected_peak")
    reason = f"Rejected resize to {rejected} because the projected CPU peak is {projected}"
    if two_step is not None:
        reason = f"{reason}. A two-step drop would project {two_step}"
    return reason


_BUILDERS = {
    "idle_compute": _idle,
    "compute_rightsizing": _rightsizing,
    "development_scheduling": _scheduling,
    "unattached_storage": _unattached,
    "storage_lifecycle": _lifecycle,
    "rightsizing_veto": _veto,
}


def _current_cents(
    costs: CostRecordRepository,
    resource_id: str,
    evidence: list[str],
) -> int | None:
    text = _value(evidence, "monthly_cost_cents")
    if text is not None and text.isdigit():
        return int(text)
    summary = costs.age_and_latest_month_cents([resource_id]).get(resource_id)
    if summary is None:
        return None
    return summary[1]


def _value(evidence: list[str], key: str) -> str | None:
    prefix = f"{key} "
    for line in evidence:
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    return None


def _dollars(cents: int) -> float:
    return round(cents / 100, 2)
