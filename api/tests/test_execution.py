from datetime import datetime, timezone

from app.execution import ExecutionRun, RealizedSavings, VerificationResult


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
