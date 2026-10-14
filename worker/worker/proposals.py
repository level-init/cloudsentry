"""Turn stored findings into Optimization Proposals.

Each MVP category has a fixed action and rollback. Costs stay in cents until
the proposal stores dollars. The compute rates and the 40/168 weekday schedule
match simulator/simulator/billing.py. Success metrics are evidence lines
because the proposal object has no separate field for them.

Risk classification is later. Every proposal stays pending and
APPROVAL_REQUIRED. A second build skips a pending proposal with the same
resource ids and the same action. A rejected proposal does not block a new one.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import create_session
from app.proposals import (
    ApprovalStatus,
    OptimizationProposal,
    RiskAssessment,
    RiskClass,
)
from app.repositories import (
    CostRecordRepository,
    DependencyRepository,
    FindingRepository,
    ProposalRepository,
    ResourceRepository,
)
from app.schemas import Resource

# Monthly cents for the compute ladder. Matches simulator/simulator/billing.py.
_COMPUTE_CENTS = {"t3.medium": 3037, "m5.large": 7008, "m5.xlarge": 14016}
_SCHEDULED_WEEK_HOURS = 40
_WEEK_HOURS = 168
_CONFIDENCE = 0.8


@dataclass(frozen=True)
class _Plan:
    action: str
    rollback: str
    current_cents: int
    predicted_cents: int
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
        existing = proposals.find_open(finding.resource_ids, plan.action)
        if existing is not None:
            skipped.append(existing)
            continue
        proposal = _proposal(session, finding, resource, plan)
        proposals.create(proposal)
        created.append(proposal)
    return ProposeResult(created=created, skipped=skipped)


def _proposal(session: Session, finding, resource: Resource, plan: _Plan) -> OptimizationProposal:
    edges = DependencyRepository(session).dependencies_of(resource.resource_id)
    evidence = list(finding.evidence)
    evidence.append(f"success_metric {plan.success_metric}")
    return OptimizationProposal(
        proposal_id=_proposal_id(session, finding.finding_id),
        finding_id=finding.finding_id,
        resource_ids=list(finding.resource_ids),
        category=finding.category,
        current_monthly_cost=_dollars(plan.current_cents),
        predicted_monthly_cost=_dollars(plan.predicted_cents),
        predicted_monthly_savings=_dollars(plan.current_cents - plan.predicted_cents),
        confidence=_CONFIDENCE,
        business_criticality=resource.business_criticality,
        evidence=evidence,
        dependencies=[f"{edge.relationship} {edge.target_resource_id}" for edge in edges],
        preconditions=plan.preconditions,
        proposed_actions=[plan.action],
        rollback_plan=[plan.rollback],
        approval_status=ApprovalStatus.pending,
        risk_assessment=_risk(),
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


def _risk() -> RiskAssessment:
    return RiskAssessment(
        risk_score=0.5,
        risk_class=RiskClass.approval_required,
        reasons=["v1 keeps the proposal pending until a person approves it"],
    )


def _idle(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    if current is None:
        return None
    return _Plan(
        action=f"stop {resource.resource_id}",
        rollback=f"start {resource.resource_id}",
        current_cents=current,
        predicted_cents=0,
        preconditions=[
            "compute is present",
            "cpu and request averages and peaks stay under the idle caps",
        ],
        success_metric="monthly cost at or below 0.00",
    )


def _rightsizing(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    recommended = _value(evidence, "recommended_sku")
    current_sku = _value(evidence, "current_sku")
    if current is None or recommended not in _COMPUTE_CENTS or not current_sku:
        return None
    predicted = _COMPUTE_CENTS[recommended]
    return _Plan(
        action=f"resize {resource.resource_id} to {recommended}",
        rollback=f"resize {resource.resource_id} to {current_sku}",
        current_cents=current,
        predicted_cents=predicted,
        preconditions=[
            f"recommended sku is {recommended}",
            "projected peak stays inside the rightsizing headroom",
        ],
        success_metric=f"monthly cost at or below {_dollars(predicted):.2f}",
    )


def _scheduling(resource: Resource, evidence: list[str], current: int | None) -> _Plan | None:
    if current is None:
        return None
    predicted = current * _SCHEDULED_WEEK_HOURS // _WEEK_HOURS
    return _Plan(
        action=f"schedule {resource.resource_id} weekdays-09-17",
        rollback=f"schedule {resource.resource_id} always_on",
        current_cents=current,
        predicted_cents=predicted,
        preconditions=[
            "environment is development or staging",
            "weekend and weekday cpu averages stay at or above 20",
        ],
        success_metric=f"monthly cost at or below {_dollars(predicted):.2f}",
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
        current_cents=current,
        predicted_cents=0,
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
    if action == "transition-to-infrequent-access":
        predicted = current // 2
        return _Plan(
            action=f"transition {resource.resource_id} to infrequent_access",
            rollback=f"transition {resource.resource_id} to standard",
            current_cents=current,
            predicted_cents=predicted,
            preconditions=[
                "storage class is standard",
                "monthly cost meets the lifecycle floor",
            ],
            success_metric=f"monthly cost at or below {_dollars(predicted):.2f}",
        )
    if action.startswith("expire-after-"):
        return _Plan(
            action=f"expire {resource.resource_id}",
            rollback=(
                f"recreate {resource.resource_id} from its source disk while that disk still exists"
            ),
            current_cents=current,
            predicted_cents=0,
            preconditions=[
                "snapshot is outside production",
                "nothing depends on the snapshot",
                "cost history meets the retention age",
            ],
            success_metric="monthly cost at or below 0.00",
        )
    return None


_BUILDERS = {
    "idle_compute": _idle,
    "compute_rightsizing": _rightsizing,
    "development_scheduling": _scheduling,
    "unattached_storage": _unattached,
    "storage_lifecycle": _lifecycle,
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
