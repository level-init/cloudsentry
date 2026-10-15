from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.approval import require_transition
from app.db import sqlalchemy_database_url
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
from app.repositories import ProposalRepository
from app.tables import FindingRow

_STATUSES = tuple(ApprovalStatus)
_LEGAL = {
    (ApprovalStatus.pending, ApprovalStatus.approved),
    (ApprovalStatus.pending, ApprovalStatus.rejected),
    (ApprovalStatus.pending, ApprovalStatus.cancelled),
}


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(sqlalchemy_database_url())
    try:
        connection = engine.connect()
    except Exception as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    transaction = connection.begin()
    bound = Session(bind=connection)
    try:
        yield bound
    finally:
        bound.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.mark.parametrize("current", _STATUSES)
@pytest.mark.parametrize("target", _STATUSES)
def test_transition_table(current: ApprovalStatus, target: ApprovalStatus) -> None:
    if (current, target) in _LEGAL:
        require_transition(current, target)
        return
    match = "re-approve" if current == target == ApprovalStatus.approved else "cannot change"
    with pytest.raises(ValueError, match=match):
        require_transition(current, target)


def test_approval_records_actor_time_and_reason_and_cannot_be_repeated(
    session: Session,
) -> None:
    session.add(
        FindingRow(
            finding_id="find-approve",
            resource_ids=["i-approve"],
            category="idle_compute",
            summary="idle instance",
            evidence=["low cpu"],
        )
    )
    session.flush()
    when = datetime(2026, 10, 15, 16, tzinfo=timezone.utc)
    repository = ProposalRepository(session)
    repository.create(_proposal())

    with pytest.raises(ValueError, match="actor and a reason"):
        repository.update_status("opt-approve", approval_status=ApprovalStatus.approved)

    updated = repository.update_status(
        "opt-approve",
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="the idle instance can stop",
        decided_at=when,
    )
    recorded = repository.decisions("opt-approve")

    assert updated is not None
    assert updated.approval_status == "approved"
    assert len(recorded) == 1
    assert recorded[0].actor == "ada"
    assert recorded[0].reason == "the idle instance can stop"
    assert recorded[0].decided_at == when
    assert recorded[0].from_status == "pending"
    assert recorded[0].to_status == "approved"
    with pytest.raises(ValueError, match="re-approve"):
        repository.update_status(
            "opt-approve",
            approval_status=ApprovalStatus.approved,
            actor="ada",
            reason="approve it again",
        )
    fetched = repository.get("opt-approve")
    assert fetched is not None
    assert fetched.approval_status == "approved"


def _proposal() -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id="opt-approve",
        finding_id="find-approve",
        resource_ids=["i-approve"],
        category="idle_compute",
        current_monthly_cost=30.37,
        predicted_monthly_cost=0,
        predicted_monthly_savings=30.37,
        confidence=0.8,
        business_criticality="low",
        evidence=["low cpu"],
        preconditions=["compute is present"],
        proposed_actions=["stop i-approve"],
        rollback_plan=["start i-approve"],
        success_metrics=["monthly cost at or below 0.00"],
        risk_assessment=RiskAssessment(
            risk_score=0.05,
            risk_class="SAFE_AUTOMATION",
            reasons=["development resource"],
        ),
    )
