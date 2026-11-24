from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.adapters import ApplyError, SimulatorApplyAdapter, dry_run_execution
from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
from app.repositories import ExecutionRunRepository, ProposalRepository
from app.schemas import Resource
from app.tables import FindingRow
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


def test_dry_run_writes_iac_and_leaves_simulator_unchanged(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session)
    before = adapter._resource("i-dev-026")
    assert before["schedule"] == "always_on"

    client = _api_client(session)
    pending = client.post(
        "/proposals/opt-i7-schedule/execute",
        params={"dry_run": True},
        headers={"X-Actor": "ada"},
    )
    approved = client.post(
        "/proposals/opt-i7-schedule/approve",
        headers={"X-Actor": "ada"},
        json={"reason": "development schedule is allowed"},
    )
    preview = dry_run_execution(
        session,
        "opt-i7-schedule",
        actor="ada",
        adapter=adapter,
    )
    via_http = client.post(
        "/proposals/opt-i7-schedule/execute",
        params={"dry_run": True},
        headers={"X-Actor": "ada"},
    )
    proposal = ProposalRepository(session).get("opt-i7-schedule")
    run = ExecutionRunRepository(session).for_proposal("opt-i7-schedule")
    after = adapter._resource("i-dev-026")

    assert pending.status_code == 409
    assert "must be approved" in pending.json()["detail"]
    assert approved.status_code == 200
    assert preview.dry_run is True
    assert preview.proposal_id == "opt-i7-schedule"
    assert preview.plan_snapshot == ["schedule i-dev-026 weekdays-09-17"]
    assert preview.preconditions == ["compute is present"]
    assert Path(preview.artifact_path).joinpath("main.tf").is_file()
    assert Path(preview.artifact_path).joinpath("commit.json").is_file()
    assert via_http.status_code == 200
    assert via_http.json()["dry_run"] is True
    assert via_http.json()["artifact_hash"] == preview.artifact_hash
    assert proposal is not None
    assert proposal.execution_status.value == "not_started"
    assert run is None
    assert after == before


def test_pending_proposal_cannot_dry_run(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session)
    before = adapter._resource("i-dev-026")

    with pytest.raises(ApplyError, match="must be approved"):
        dry_run_execution(session, "opt-i7-schedule", actor="ada", adapter=adapter)

    assert adapter._resource("i-dev-026") == before
    assert ProposalRepository(session).get("opt-i7-schedule").execution_status.value == (
        "not_started"
    )


def test_dry_run_refuses_missing_resource(
    session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session, resource_id="i-missing-i7")
    ProposalRepository(session).update_status(
        "opt-i7-schedule",
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="approved for missing resource check",
    )

    with pytest.raises(ApplyError, match="precondition failed"):
        dry_run_execution(session, "opt-i7-schedule", actor="ada")


def test_openapi_lists_dry_run_on_execute() -> None:
    schema = create_app().openapi()
    execute = schema["paths"]["/proposals/{proposal_id}/execute"]["post"]
    names = {item["name"] for item in execute["parameters"]}

    assert "dry_run" in names
    assert "X-Actor" in names


def _seed_schedule(session: Session, *, resource_id: str = "i-dev-026") -> None:
    if resource_id == "i-dev-026":
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
            finding_id="find-i7-schedule",
            resource_ids=[resource_id],
            category="development_scheduling",
            summary="schedule a development instance",
            evidence=["weekend cpu"],
        )
    )
    session.flush()
    ProposalRepository(session).create(
        OptimizationProposal(
            proposal_id="opt-i7-schedule",
            finding_id="find-i7-schedule",
            resource_ids=[resource_id],
            category="development_scheduling",
            current_monthly_cost=70.08,
            predicted_monthly_cost=16.68,
            predicted_monthly_savings=53.4,
            confidence=0.8,
            business_criticality="low",
            evidence=["weekend cpu"],
            preconditions=["compute is present"],
            proposed_actions=[f"schedule {resource_id} weekdays-09-17"],
            rollback_plan=[f"schedule {resource_id} always_on"],
            success_metrics=["weekday schedule is set"],
            approval_status="pending",
            risk_assessment=RiskAssessment(
                risk_score=0.05,
                risk_class="SAFE_AUTOMATION",
                reasons=["development resource"],
            ),
        )
    )


def _api_client(session: Session) -> TestClient:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)
