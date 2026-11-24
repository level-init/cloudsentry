from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.adapters import (
    PolicyProhibitedError,
    SimulatorApplyAdapter,
    apply_approved_plan,
)
from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
from app.repositories import ExecutionRunRepository, PolicyRepository, ProposalRepository
from app.schemas import Policy, Resource
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


def test_policy_change_after_approve_blocks_apply_without_sim_change(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session)
    PolicyRepository(session).seed_defaults()
    ProposalRepository(session).update_status(
        "opt-i9-schedule",
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="development schedule is allowed",
    )
    before = adapter._resource("i-dev-026")
    assert before["schedule"] == "always_on"

    PolicyRepository(session).upsert(
        Policy(
            name="prohibit-development-schedule-race",
            effect="prohibit",
            actions=["schedule"],
            environment="development",
            resource_type="compute",
        )
    )

    with pytest.raises(PolicyProhibitedError, match="policy_prohibited") as raised:
        apply_approved_plan(session, "opt-i9-schedule", actor="ada", adapter=adapter)

    client = _api_client(session)
    via_http = client.post(
        "/proposals/opt-i9-schedule/apply",
        headers={"X-Actor": "ada"},
    )
    after = adapter._resource("i-dev-026")
    run = ExecutionRunRepository(session).for_proposal("opt-i9-schedule")

    assert raised.value.code == "policy_prohibited"
    assert raised.value.policy_name == "prohibit-development-schedule-race"
    assert via_http.status_code == 409
    assert via_http.json()["detail"].startswith("policy_prohibited:")
    assert after == before
    assert run is None


def test_already_approved_prohibited_delete_cannot_mutate(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    ensure_resource(
        session,
        Resource(
            resource_id="db-i9-prd",
            resource_type="database",
            account_id="111111111111",
            environment="production",
            owner="payments",
            team="payments",
            business_criticality="high",
            tags={"environment": "production", "owner": "payments", "team": "payments"},
        ),
    )
    session.add(
        FindingRow(
            finding_id="find-i9-delete",
            resource_ids=["db-i9-prd"],
            category="unattached_storage",
            summary="delete a production database",
            evidence=["unused"],
        )
    )
    session.flush()
    PolicyRepository(session).seed_defaults()
    ProposalRepository(session).create(
        OptimizationProposal(
            proposal_id="opt-i9-delete",
            finding_id="find-i9-delete",
            resource_ids=["db-i9-prd"],
            category="unattached_storage",
            current_monthly_cost=100.0,
            predicted_monthly_cost=0.0,
            predicted_monthly_savings=100.0,
            confidence=0.5,
            business_criticality="high",
            evidence=["unused"],
            preconditions=["database is present"],
            proposed_actions=["delete db-i9-prd"],
            rollback_plan=["restore db-i9-prd"],
            success_metrics=["database is gone"],
            approval_status="approved",
            risk_assessment=RiskAssessment(
                risk_score=0.9,
                risk_class="REJECTED",
                reasons=["production database"],
            ),
        )
    )
    # Inventory resource only — assert apply refuses before any mutate attempt.
    with pytest.raises(PolicyProhibitedError, match="policy_prohibited") as raised:
        apply_approved_plan(session, "opt-i9-delete", actor="ada", adapter=adapter)

    assert raised.value.policy_name == "prohibit-delete-production-database"
    assert ExecutionRunRepository(session).for_proposal("opt-i9-delete") is None


def test_queued_run_still_blocked_when_policy_turns_prohibit(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session)
    PolicyRepository(session).seed_defaults()
    ProposalRepository(session).update_status(
        "opt-i9-schedule",
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="development schedule is allowed",
    )
    ProposalRepository(session).begin_execution("opt-i9-schedule", actor="ada")
    before = adapter._resource("i-dev-026")
    PolicyRepository(session).upsert(
        Policy(
            name="prohibit-development-schedule-queued",
            effect="prohibit",
            actions=["schedule"],
            environment="development",
            resource_type="compute",
        )
    )

    with pytest.raises(PolicyProhibitedError, match="policy_prohibited"):
        apply_approved_plan(session, "opt-i9-schedule", actor="ada", adapter=adapter)

    run = ExecutionRunRepository(session).for_proposal("opt-i9-schedule")
    assert run is not None
    assert run.status.value == "queued"
    assert adapter._resource("i-dev-026") == before
    assert ExecutionRunRepository(session).events(run.execution_id) == []


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
            finding_id="find-i9-schedule",
            resource_ids=["i-dev-026"],
            category="development_scheduling",
            summary="schedule a development instance",
            evidence=["weekend cpu"],
        )
    )
    session.flush()
    ProposalRepository(session).create(
        OptimizationProposal(
            proposal_id="opt-i9-schedule",
            finding_id="find-i9-schedule",
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
