from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.adapters import SimulatorApplyAdapter, apply_approved_plan
from app.db import sqlalchemy_database_url
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
from app.repositories import ProposalRepository, VerificationResultRepository
from app.schemas import Resource
from app.tables import FindingRow
from simulator.main import create_app as create_simulator
from tests.support import ensure_resource, simulator_request

_START = datetime(2026, 4, 1, tzinfo=timezone.utc)
_PLUS_SEVEN = datetime(2026, 4, 8, tzinfo=timezone.utc)


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


@pytest.fixture
def adapter() -> SimulatorApplyAdapter:
    client = TestClient(create_simulator())
    return SimulatorApplyAdapter(base_url="http://simulator", request=simulator_request(client))


def test_apply_advances_seven_day_observation_window_in_seconds(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    monkeypatch.setenv("OBSERVATION_WINDOW_DAYS", "7")
    _seed_schedule(session)
    _approve(session, "opt-j2-schedule")
    assert adapter.read_clock() == _START

    applied = apply_approved_plan(session, "opt-j2-schedule", actor="ada", adapter=adapter)
    again = apply_approved_plan(session, "opt-j2-schedule", actor="ada", adapter=adapter)
    verification = VerificationResultRepository(session).for_execution(applied.execution_id)

    assert applied.status.value == "succeeded"
    assert adapter.read_clock() == _PLUS_SEVEN
    assert verification is not None
    assert verification.status.value == "inconclusive"
    assert verification.observation_window is not None
    assert verification.observation_window.start == _START
    assert verification.observation_window.end == _PLUS_SEVEN
    assert verification.observation_window.grain == "day"
    assert verification.post_change is not None
    assert len(verification.post_change) == 1
    post = verification.post_change[0]
    assert post.resource_id == "i-dev-026"
    assert post.cost.amount_cents > 0
    assert post.metrics[0].name == "cpu_percent"
    assert post.metrics[0].sample_count == 7 * 24
    assert again.execution_id == applied.execution_id
    assert VerificationResultRepository(session).for_execution(applied.execution_id) == (
        verification
    )


def _seed_schedule(session: Session) -> None:
    ensure_resource(
        session,
        Resource(
            resource_id="i-dev-026",
            resource_type="compute",
            account_id="111111111111",
            environment="development",
            owner="payments",
            team="payments",
            business_criticality="low",
            tags={"environment": "development", "owner": "payments", "team": "payments"},
            sku="m5.large",
        ),
    )
    session.add(
        FindingRow(
            finding_id="find-j2-schedule",
            resource_ids=["i-dev-026"],
            category="development_scheduling",
            summary="schedule a development instance",
            evidence=["weekend cpu"],
        )
    )
    session.flush()
    ProposalRepository(session).create(
        OptimizationProposal(
            proposal_id="opt-j2-schedule",
            finding_id="find-j2-schedule",
            resource_ids=["i-dev-026"],
            category="development_scheduling",
            current_monthly_cost=70.08,
            predicted_monthly_cost=16.68,
            predicted_monthly_savings=53.4,
            confidence=0.8,
            business_criticality="low",
            evidence=["weekend cpu"],
            preconditions=["compute is present"],
            proposed_actions=["schedule i-dev-026 weekdays-09-17"],
            rollback_plan=["schedule i-dev-026 always_on"],
            success_metrics=["weekday schedule is set"],
            approval_status="pending",
            risk_assessment=RiskAssessment(
                risk_score=0.05,
                risk_class="SAFE_AUTOMATION",
                reasons=["development resource"],
            ),
        )
    )


def _approve(session: Session, proposal_id: str) -> None:
    ProposalRepository(session).update_status(
        proposal_id,
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="development schedule is allowed",
    )
