from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.adapters import SimulatorApplyAdapter, apply_approved_plan, rollback_execution
from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
from app.repositories import ExecutionRunRepository, ProposalRepository
from app.schemas import Resource
from app.tables import ExecutionEventRow, FindingRow
from simulator.main import create_app as create_simulator
from tests.support import ensure_resource, simulator_request


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


def test_apply_and_rollback_append_execution_audit(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session)
    _approve(session, "opt-i8-schedule")

    applied = apply_approved_plan(session, "opt-i8-schedule", actor="ada", adapter=adapter)
    client = _api_client(session)
    after_apply = client.get(f"/executions/{applied.execution_id}/audit")
    rolled = rollback_execution(
        session,
        "opt-i8-schedule",
        actor="ada",
        reason="morning job missed its window",
        adapter=adapter,
    )
    after_rollback = client.get(f"/executions/{rolled.execution_id}/audit")
    missing = client.get("/executions/execution-missing/audit")
    events = ExecutionRunRepository(session).events(applied.execution_id)

    assert after_apply.status_code == 200
    assert len(after_apply.json()) == 1
    assert after_apply.json()[0]["event_type"] == "apply"
    assert after_apply.json()[0]["actor"] == "ada"
    assert after_apply.json()[0]["reason"] == "applied approved plan"
    assert after_apply.json()[0]["to_status"] == "succeeded"
    assert after_rollback.status_code == 200
    assert len(after_rollback.json()) == 2
    assert after_rollback.json()[1]["event_type"] == "rollback"
    assert after_rollback.json()[1]["reason"] == "morning job missed its window"
    assert after_rollback.json()[1]["to_status"] == "rolled_back"
    assert missing.status_code == 404
    assert len(events) == 2
    assert events[0].event_type.value == "apply"
    assert events[1].event_type.value == "rollback"


def test_execution_audit_rows_cannot_be_updated_or_deleted(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session)
    _approve(session, "opt-i8-schedule")
    applied = apply_approved_plan(session, "opt-i8-schedule", actor="ada", adapter=adapter)

    with pytest.raises(DBAPIError, match="append-only"):
        with session.begin_nested():
            session.execute(
                update(ExecutionEventRow)
                .where(ExecutionEventRow.execution_id == applied.execution_id)
                .values(reason="tampered")
            )
            session.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        with session.begin_nested():
            session.execute(
                delete(ExecutionEventRow).where(
                    ExecutionEventRow.execution_id == applied.execution_id
                )
            )
            session.flush()

    recorded = ExecutionRunRepository(session).events(applied.execution_id)
    assert len(recorded) == 1
    assert recorded[0].reason == "applied approved plan"


def test_openapi_lists_execution_audit_route() -> None:
    schema = create_app().openapi()
    audit = schema["paths"]["/executions/{execution_id}/audit"]["get"]

    assert audit["tags"] == ["executions"]


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
            finding_id="find-i8-schedule",
            resource_ids=["i-dev-026"],
            category="development_scheduling",
            summary="schedule a development instance",
            evidence=["weekend cpu"],
        )
    )
    session.flush()
    ProposalRepository(session).create(
        OptimizationProposal(
            proposal_id="opt-i8-schedule",
            finding_id="find-i8-schedule",
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


def _api_client(session: Session) -> TestClient:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)
