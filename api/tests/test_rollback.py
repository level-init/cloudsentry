from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.adapters import (
    ApplyError,
    SimulatorApplyAdapter,
    apply_approved_plan,
    rollback_execution,
)
from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
from app.repositories import ProposalRepository
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


def test_apply_then_rollback_restores_dev_schedule(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed(
        session,
        "opt-i6-schedule",
        "find-i6-schedule",
        "i-dev-026",
        "development_scheduling",
        ["schedule i-dev-026 weekdays-09-17"],
        ["schedule i-dev-026 always_on"],
    )
    before = adapter._resource("i-dev-026")["schedule"]
    _approve(session, "opt-i6-schedule")
    applied = apply_approved_plan(session, "opt-i6-schedule", actor="ada", adapter=adapter)
    during = adapter._resource("i-dev-026")["schedule"]
    rolled = rollback_execution(
        session,
        "opt-i6-schedule",
        actor="ada",
        reason="morning job missed its window",
        adapter=adapter,
    )
    again = rollback_execution(
        session,
        "opt-i6-schedule",
        actor="ada",
        reason="already rolled back",
        adapter=adapter,
    )
    after = adapter._resource("i-dev-026")["schedule"]

    assert before == "always_on"
    assert applied.status.value == "succeeded"
    assert applied.applied_action_ids
    assert during == "weekdays-09-17"
    assert rolled.status.value == "rolled_back"
    assert rolled.rolled_back_by == "ada"
    assert rolled.rollback_reason == "morning job missed its window"
    assert rolled.finished_at is not None
    assert again.execution_id == rolled.execution_id
    assert after == before


def test_rollback_restores_stop_resize_delete_and_lifecycle(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    cases = [
        (
            "opt-i6-stop",
            "find-i6-stop",
            "i-dev-062",
            "idle_compute",
            ["stop i-dev-062"],
            ["start i-dev-062"],
            lambda: adapter._resource("i-dev-062")["power_state"],
            "running",
            "stopped",
        ),
        (
            "opt-i6-resize",
            "find-i6-resize",
            "i-prd-013",
            "compute_rightsizing",
            ["resize i-prd-013 to m5.large"],
            ["resize i-prd-013 to m5.xlarge"],
            lambda: adapter._resource("i-prd-013")["sku"],
            "m5.xlarge",
            "m5.large",
        ),
        (
            "opt-i6-delete",
            "find-i6-delete",
            "vol-dev-042",
            "unattached_storage",
            ["delete vol-dev-042"],
            ["recreate vol-dev-042"],
            lambda: adapter._resource("vol-dev-042") is not None,
            True,
            False,
        ),
        (
            "opt-i6-lifecycle",
            "find-i6-lifecycle",
            "bucket-prd-022",
            "storage_lifecycle",
            ["transition bucket-prd-022 to infrequent_access"],
            ["transition bucket-prd-022 to standard"],
            lambda: adapter._resource("bucket-prd-022")["storage_class"],
            "standard",
            "infrequent_access",
        ),
    ]
    for (
        proposal_id,
        finding_id,
        resource_id,
        category,
        actions,
        rollback,
        read,
        before_value,
        during_value,
    ) in cases:
        _seed(session, proposal_id, finding_id, resource_id, category, actions, rollback)
        assert read() == before_value
        _approve(session, proposal_id)
        apply_approved_plan(session, proposal_id, actor="ada", adapter=adapter)
        assert read() == during_value
        rolled = rollback_execution(
            session,
            proposal_id,
            actor="ada",
            reason=f"undo {proposal_id}",
            adapter=adapter,
        )
        assert rolled.status.value == "rolled_back"
        assert rolled.rolled_back_by == "ada"
        assert read() == before_value


def test_rollback_http_requires_actor_and_reason(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed(
        session,
        "opt-i6-http",
        "find-i6-http",
        "i-dev-026",
        "development_scheduling",
        ["schedule i-dev-026 weekdays-09-17"],
        ["schedule i-dev-026 always_on"],
    )
    _approve(session, "opt-i6-http")
    apply_approved_plan(session, "opt-i6-http", actor="ada", adapter=adapter)
    monkeypatch.setattr(
        "app.proposal_api.rollback_execution",
        lambda session, proposal_id, actor, reason: rollback_execution(
            session,
            proposal_id,
            actor=actor,
            reason=reason,
            adapter=adapter,
        ),
    )
    client = _api_client(session)
    missing = client.post(
        "/proposals/opt-i6-http/rollback",
        json={"reason": "morning job missed its window"},
    )
    blank = client.post(
        "/proposals/opt-i6-http/rollback",
        headers={"X-Actor": "ada"},
        json={"reason": " "},
    )
    rolled = client.post(
        "/proposals/opt-i6-http/rollback",
        headers={"X-Actor": "ada"},
        json={"reason": "morning job missed its window"},
    )

    assert missing.status_code == 422
    assert blank.status_code == 422
    assert rolled.status_code == 200
    assert rolled.json()["status"] == "rolled_back"
    assert rolled.json()["rolled_back_by"] == "ada"
    assert rolled.json()["rollback_reason"] == "morning job missed its window"
    assert adapter._resource("i-dev-026")["schedule"] == "always_on"


def test_openapi_lists_rollback_route() -> None:
    schema = create_app().openapi()
    route = schema["paths"]["/proposals/{proposal_id}/rollback"]["post"]

    assert route["tags"] == ["proposals"]
    assert "X-Actor" in {item["name"] for item in route["parameters"]}


def test_cannot_roll_back_before_success(
    session: Session,
    adapter: SimulatorApplyAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TERRAFORM_CHANGES_DIR", str(tmp_path))
    _seed(
        session,
        "opt-i6-early",
        "find-i6-early",
        "i-dev-026",
        "development_scheduling",
        ["schedule i-dev-026 weekdays-09-17"],
        ["schedule i-dev-026 always_on"],
    )
    _approve(session, "opt-i6-early")
    ProposalRepository(session).begin_execution("opt-i6-early", actor="ada")

    with pytest.raises(ApplyError, match="must be succeeded"):
        rollback_execution(
            session,
            "opt-i6-early",
            actor="ada",
            reason="too early",
            adapter=adapter,
        )


def _approve(session: Session, proposal_id: str) -> None:
    ProposalRepository(session).update_status(
        proposal_id,
        approval_status=ApprovalStatus.approved,
        actor="ada",
        reason="ready to apply",
    )


def _seed(
    session: Session,
    proposal_id: str,
    finding_id: str,
    resource_id: str,
    category: str,
    actions: list[str],
    rollback: list[str],
) -> None:
    resource_type = "compute"
    if resource_id.startswith("vol-"):
        resource_type = "disk"
    elif resource_id.startswith("bucket-"):
        resource_type = "object_storage"
    environment = "development"
    if resource_id.startswith("i-prd") or resource_id.startswith("bucket-prd"):
        environment = "production"
    ensure_resource(
        session,
        Resource(
            resource_id=resource_id,
            resource_type=resource_type,
            account_id="111111111111" if environment == "development" else "333333333333",
            environment=environment,
            owner="payments",
            team="payments",
            business_criticality="low",
            tags={"environment": environment, "owner": "payments", "team": "payments"},
            sku="m5.large",
            storage_class="standard" if resource_type == "object_storage" else None,
        ),
    )
    session.add(
        FindingRow(
            finding_id=finding_id,
            resource_ids=[resource_id],
            category=category,
            summary=f"{resource_id} {category}",
            evidence=["planted for rollback"],
        )
    )
    session.flush()
    ProposalRepository(session).create(
        OptimizationProposal(
            proposal_id=proposal_id,
            finding_id=finding_id,
            resource_ids=[resource_id],
            category=category,
            current_monthly_cost=70.08,
            predicted_monthly_cost=16.68,
            predicted_monthly_savings=53.4,
            confidence=0.8,
            business_criticality="low",
            evidence=["planted for rollback"],
            preconditions=["resource is present"],
            proposed_actions=actions,
            rollback_plan=rollback,
            success_metrics=["change is reversible"],
            approval_status="pending",
            risk_assessment=RiskAssessment(
                risk_score=0.05,
                risk_class="SAFE_AUTOMATION",
                reasons=["fixture"],
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
