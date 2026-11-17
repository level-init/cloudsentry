from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.execution import (
    ExecutionRun,
    RealizedSavings,
    VerificationResult,
    require_run_transition,
)
from app.proposals import ApprovalStatus, ExecutionStatus, OptimizationProposal, RiskAssessment
from app.repositories import ExecutionRunRepository, ProposalRepository
from app.tables import FindingRow

_STATUSES = (
    ExecutionStatus.queued,
    ExecutionStatus.running,
    ExecutionStatus.succeeded,
    ExecutionStatus.failed,
    ExecutionStatus.rolled_back,
)
_LEGAL = {
    (ExecutionStatus.queued, ExecutionStatus.running),
    (ExecutionStatus.queued, ExecutionStatus.failed),
    (ExecutionStatus.running, ExecutionStatus.succeeded),
    (ExecutionStatus.running, ExecutionStatus.failed),
    (ExecutionStatus.running, ExecutionStatus.rolled_back),
    (ExecutionStatus.succeeded, ExecutionStatus.rolled_back),
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
def test_run_transition_table(current: ExecutionStatus, target: ExecutionStatus) -> None:
    if (current, target) in _LEGAL:
        require_run_transition(current, target)
        return
    match = "already" if current == target else "cannot change"
    with pytest.raises(ValueError, match=match):
        require_run_transition(current, target)


def test_execution_run_is_created_and_reaches_terminal_states(session: Session) -> None:
    session.add(
        FindingRow(
            finding_id="find-i1",
            resource_ids=["i-i1"],
            category="idle_compute",
            summary="idle instance",
            evidence=["low cpu"],
        )
    )
    session.flush()
    proposals = ProposalRepository(session)
    proposals.create(_proposal())
    proposals.update_status(
        "opt-i1",
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="the idle instance can stop",
    )
    when = datetime(2026, 10, 15, 18, tzinfo=timezone.utc)

    queued = proposals.begin_execution("opt-i1", actor="ada")
    runs = ExecutionRunRepository(session)
    created = runs.for_proposal("opt-i1")
    again = proposals.begin_execution("opt-i1", actor="ada")
    same = runs.for_proposal("opt-i1")

    assert queued is not None
    assert queued.execution_status == "queued"
    assert created is not None
    assert created.execution_id == "execution-opt-i1"
    assert created.proposal_id == "opt-i1"
    assert created.status == ExecutionStatus.queued
    assert created.actor == "ada"
    assert created.plan_snapshot == ["stop i-i1"]
    assert created.rollback_plan == ["start i-i1"]
    assert created.finished_at is None
    assert again is not None
    assert same is not None
    assert same.execution_id == created.execution_id

    running = runs.update_status("execution-opt-i1", ExecutionStatus.running)
    assert running is not None
    assert running.status == ExecutionStatus.running
    assert proposals.get("opt-i1").execution_status == "running"

    succeeded = runs.update_status(
        "execution-opt-i1",
        ExecutionStatus.succeeded,
        finished_at=when,
    )
    assert succeeded is not None
    assert succeeded.status == ExecutionStatus.succeeded
    assert succeeded.finished_at == when
    assert proposals.get("opt-i1").execution_status == "succeeded"

    with pytest.raises(ValueError, match="cannot change"):
        runs.update_status("execution-opt-i1", ExecutionStatus.failed)

    rolled = runs.update_status(
        "execution-opt-i1",
        ExecutionStatus.rolled_back,
        rollback_reason="morning job missed its window",
        rolled_back_by="ada",
        finished_at=when,
    )
    assert rolled is not None
    assert rolled.status == ExecutionStatus.rolled_back
    assert rolled.rollback_reason == "morning job missed its window"
    assert rolled.rolled_back_by == "ada"
    assert proposals.get("opt-i1").execution_status == "rolled_back"

    failed_path = _failed_run(session)
    assert failed_path.status == ExecutionStatus.failed
    assert failed_path.finished_at is not None


def test_execution_verification_and_savings_share_proposal_id() -> None:
    started_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    finished_at = datetime(2026, 3, 1, 0, 5, tzinfo=timezone.utc)
    run = ExecutionRun(
        execution_id="run-1",
        proposal_id="opt-1042",
        status="rolled_back",
        actor="lewi7",
        plan_snapshot=["stop the instance outside business hours"],
        started_at=started_at,
        finished_at=finished_at,
        rollback_plan=["start the instance and remove the schedule"],
        rollback_reason="morning job missed its window",
        rolled_back_by="cloudsentry",
    )
    result = VerificationResult(
        verification_id="ver-1",
        proposal_id=run.proposal_id,
        execution_id=run.execution_id,
        status="rollback",
        predicted_monthly_savings=182.4,
        realized_monthly_savings=40.0,
        operational_impact="one delayed morning job",
    )
    savings = RealizedSavings(
        savings_id="sav-1",
        proposal_id=result.proposal_id,
        verification_id=result.verification_id,
        amount=result.realized_monthly_savings,
        period_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )

    assert run.proposal_id == result.proposal_id == savings.proposal_id == "opt-1042"
    assert result.status == "rollback"
    assert run.rollback_reason == "morning job missed its window"
    assert savings.amount == 40.0


def test_verification_outcomes_cover_required_statuses() -> None:
    statuses = {"success", "partial", "rollback", "inconclusive"}
    for status in statuses:
        result = VerificationResult(
            verification_id=f"ver-{status}",
            proposal_id="opt-1042",
            execution_id="run-1",
            status=status,
            predicted_monthly_savings=100,
            realized_monthly_savings=80,
            operational_impact="none detected",
        )
        assert result.status == status


def _failed_run(session: Session) -> ExecutionRun:
    session.add(
        FindingRow(
            finding_id="find-i1-fail",
            resource_ids=["i-i1-fail"],
            category="idle_compute",
            summary="idle instance",
            evidence=["low cpu"],
        )
    )
    session.flush()
    proposals = ProposalRepository(session)
    proposals.create(_proposal("opt-i1-fail", "find-i1-fail", "i-i1-fail"))
    proposals.update_status(
        "opt-i1-fail",
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="ready to stop",
    )
    proposals.begin_execution("opt-i1-fail", actor="ada")
    runs = ExecutionRunRepository(session)
    runs.update_status("execution-opt-i1-fail", ExecutionStatus.running)
    return runs.update_status("execution-opt-i1-fail", ExecutionStatus.failed)


def _proposal(
    proposal_id: str = "opt-i1",
    finding_id: str = "find-i1",
    resource_id: str = "i-i1",
) -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id=proposal_id,
        finding_id=finding_id,
        resource_ids=[resource_id],
        category="idle_compute",
        current_monthly_cost=30.37,
        predicted_monthly_cost=0,
        predicted_monthly_savings=30.37,
        confidence=0.8,
        business_criticality="low",
        evidence=["low cpu"],
        preconditions=["compute is present"],
        proposed_actions=[f"stop {resource_id}"],
        rollback_plan=[f"start {resource_id}"],
        success_metrics=["monthly cost at or below 0.00"],
        approval_status="pending",
        risk_assessment=RiskAssessment(
            risk_score=0.05,
            risk_class="SAFE_AUTOMATION",
            reasons=["development resource"],
        ),
    )
