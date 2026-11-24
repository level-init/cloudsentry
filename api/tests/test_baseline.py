from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.adapters import ApplyError, SimulatorApplyAdapter, apply_approved_plan
from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
from app.repositories import ExecutionRunRepository, ProposalRepository
from app.schemas import Resource
from app.tables import FindingRow
from simulator.main import create_app as create_simulator
from tests.support import ensure_resource


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
    return SimulatorApplyAdapter(base_url="http://simulator", request=_client_request(client))


def test_apply_captures_immutable_pre_change_baseline(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session)
    _approve(session, "opt-j1-schedule")
    before_costs = adapter.read_costs("i-dev-026")

    applied = apply_approved_plan(session, "opt-j1-schedule", actor="ada", adapter=adapter)
    again = apply_approved_plan(session, "opt-j1-schedule", actor="ada", adapter=adapter)
    via_http = _api_client(session).get(f"/executions/{applied.execution_id}")

    assert applied.baseline is not None
    assert applied.baseline.source == "simulator"
    assert len(applied.baseline.resources) == 1
    resource = applied.baseline.resources[0]
    assert resource.resource_id == "i-dev-026"
    assert resource.cost.amount_cents == before_costs["total_cents"]
    assert resource.cost.window.year == before_costs["year"]
    assert resource.cost.window.month == before_costs["month"]
    assert resource.cost.window.grain == "day"
    assert resource.metrics[0].name == "cpu_percent"
    assert resource.metrics[0].sample_count > 0
    assert resource.metrics[0].average is not None
    assert resource.metrics[0].peak is not None
    assert resource.metrics[0].window.grain == "hour"
    assert again.baseline == applied.baseline
    assert via_http.status_code == 200
    assert (
        via_http.json()["baseline"]["resources"][0]["cost"]["amount_cents"]
        == (before_costs["total_cents"])
    )


def test_missing_simulator_resource_blocks_apply_without_mutate(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session, resource_id="i-j1-missing", in_inventory_only=True)
    _approve(session, "opt-j1-schedule")
    before = adapter._resource("i-dev-026")

    with pytest.raises(ApplyError, match="baseline cannot be captured"):
        apply_approved_plan(session, "opt-j1-schedule", actor="ada", adapter=adapter)

    run = ExecutionRunRepository(session).for_proposal("opt-j1-schedule")
    assert run is not None
    assert run.baseline is None
    assert run.status.value == "queued"
    assert adapter._resource("i-dev-026") == before


def _seed_schedule(
    session: Session,
    *,
    resource_id: str = "i-dev-026",
    in_inventory_only: bool = False,
) -> None:
    ensure_resource(
        session,
        Resource(
            resource_id=resource_id,
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
            finding_id="find-j1-schedule",
            resource_ids=[resource_id],
            category="development_scheduling",
            summary="schedule a development instance",
            evidence=["weekend cpu"],
        )
    )
    session.flush()
    action_id = "i-dev-026" if in_inventory_only else resource_id
    ProposalRepository(session).create(
        OptimizationProposal(
            proposal_id="opt-j1-schedule",
            finding_id="find-j1-schedule",
            resource_ids=[resource_id],
            category="development_scheduling",
            current_monthly_cost=70.08,
            predicted_monthly_cost=16.68,
            predicted_monthly_savings=53.4,
            confidence=0.8,
            business_criticality="low",
            evidence=["weekend cpu"],
            preconditions=["compute is present"],
            proposed_actions=[f"schedule {action_id} weekdays-09-17"],
            rollback_plan=[f"schedule {action_id} always_on"],
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


def _client_request(client: TestClient):
    def request(method: str, url: str, body: dict | None) -> tuple[int, object]:
        path = urlparse(url).path
        if method == "GET":
            response = client.get(path)
        else:
            response = client.request(method, path, json=body)
        if not response.content:
            return response.status_code, None
        return response.status_code, response.json()

    return request
