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
from app.proposals import OptimizationProposal, RiskAssessment
from app.repositories import ProposalRepository, ResourceRepository
from app.schemas import Resource
from app.tables import FindingRow
from simulator.main import create_app as create_simulator


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


def test_approved_dev_schedule_applies_to_the_simulator(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed_schedule(session)
    assert adapter._resource("i-dev-026")["schedule"] == "always_on"

    client = _api_client(session)
    pending = client.post(
        "/proposals/opt-i5-schedule/apply",
        headers={"X-Actor": "ada"},
    )
    approved = client.post(
        "/proposals/opt-i5-schedule/approve",
        headers={"X-Actor": "ada"},
        json={"reason": "development schedule is allowed"},
    )
    applied = apply_approved_plan(
        session,
        "opt-i5-schedule",
        actor="ada",
        adapter=adapter,
    )
    again = apply_approved_plan(
        session,
        "opt-i5-schedule",
        actor="ada",
        adapter=adapter,
    )
    via_http = client.post(
        "/proposals/opt-i5-schedule/apply",
        headers={"X-Actor": "ada"},
    )

    assert pending.status_code == 409
    assert "must be approved" in pending.json()["detail"]
    assert approved.status_code == 200
    assert applied.status.value == "succeeded"
    assert applied.finished_at is not None
    assert adapter._resource("i-dev-026")["schedule"] == "weekdays-09-17"
    assert again.execution_id == applied.execution_id
    assert again.status.value == "succeeded"
    assert via_http.status_code == 200
    assert via_http.json()["status"] == "succeeded"
    assert via_http.json()["execution_id"] == applied.execution_id


def test_pending_proposal_cannot_apply(session: Session, adapter: SimulatorApplyAdapter) -> None:
    _seed_schedule(session)

    with pytest.raises(ApplyError, match="must be approved"):
        apply_approved_plan(session, "opt-i5-schedule", actor="ada", adapter=adapter)
    assert adapter._resource("i-dev-026")["schedule"] == "always_on"


def test_openapi_lists_apply_route() -> None:
    schema = create_app().openapi()
    apply_route = schema["paths"]["/proposals/{proposal_id}/apply"]["post"]

    assert apply_route["tags"] == ["proposals"]
    assert "X-Actor" in {item["name"] for item in apply_route["parameters"]}


def _seed_schedule(session: Session) -> None:
    resources = ResourceRepository(session)
    resource = Resource(
        resource_id="i-dev-026",
        resource_type="compute",
        account_id="111111111111",
        environment="development",
        owner="payments",
        team="payments",
        business_criticality="low",
        tags={"environment": "development", "owner": "payments", "team": "payments"},
        sku="m5.large",
    )
    if resources.get("i-dev-026") is None:
        resources.create(resource)
    else:
        resources.upsert(resource)
    session.add(
        FindingRow(
            finding_id="find-i5-schedule",
            resource_ids=["i-dev-026"],
            category="development_scheduling",
            summary="schedule a development instance",
            evidence=["weekend cpu"],
        )
    )
    session.flush()
    ProposalRepository(session).create(
        OptimizationProposal(
            proposal_id="opt-i5-schedule",
            finding_id="find-i5-schedule",
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
