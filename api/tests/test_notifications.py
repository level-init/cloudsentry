from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.proposals import OptimizationProposal, RiskAssessment
from app.repositories import ProposalRepository, ResourceRepository
from app.schemas import Resource
from app.tables import FindingRow


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


def test_openapi_lists_notification_filters() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/notifications"]["get"]
    names = {item["name"] for item in operation["parameters"]}

    assert operation["tags"] == ["notifications"]
    assert {"owner", "team"} <= names


def test_pending_proposal_notifies_the_owner_and_team_from_tags(session: Session) -> None:
    ResourceRepository(session).create(
        Resource(
            resource_id="i-h5",
            resource_type="compute",
            account_id="111111111111",
            environment="development",
            owner="column-owner",
            team="column-team",
            business_criticality="low",
            tags={"owner": "owner-h5", "team": "team-h5"},
        )
    )
    session.add(
        FindingRow(
            finding_id="find-h5",
            resource_ids=["i-h5"],
            category="idle_compute",
            summary="idle instance",
            evidence=["low cpu"],
        )
    )
    session.add(
        FindingRow(
            finding_id="find-h5-rejected",
            resource_ids=["i-h5"],
            category="rightsizing_veto",
            summary="do not resize",
            evidence=["projected peak"],
        )
    )
    session.flush()
    repository = ProposalRepository(session)
    repository.create(_proposal("opt-h5", "find-h5", "pending"))
    repository.create(_proposal("opt-h5-rejected", "find-h5-rejected", "rejected"))
    client = _client(session)

    by_owner = client.get("/notifications", params={"owner": "owner-h5"})
    by_team = client.get("/notifications", params={"team": "team-h5"})
    both = client.get("/notifications", params={"owner": "owner-h5", "team": "team-h5"})
    column = client.get("/notifications", params={"owner": "column-owner"})
    other = client.get("/notifications", params={"team": "team-other"})
    missing = client.get("/notifications")

    assert by_owner.status_code == 200
    assert [item["proposal_id"] for item in by_owner.json()["items"]] == ["opt-h5"]
    assert by_owner.json()["items"][0]["owner"] == "owner-h5"
    assert by_owner.json()["items"][0]["team"] == "team-h5"
    assert by_owner.json()["items"][0]["kind"] == "pending_approval"
    assert [item["proposal_id"] for item in by_team.json()["items"]] == ["opt-h5"]
    assert [item["proposal_id"] for item in both.json()["items"]] == ["opt-h5"]
    assert "opt-h5" not in [item["proposal_id"] for item in column.json()["items"]]
    assert other.json()["items"] == []
    assert missing.status_code == 422


def _client(session: Session) -> TestClient:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def _proposal(proposal_id: str, finding_id: str, approval_status: str) -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id=proposal_id,
        finding_id=finding_id,
        resource_ids=["i-h5"],
        category="idle_compute",
        current_monthly_cost=30.37,
        predicted_monthly_cost=0,
        predicted_monthly_savings=30.37,
        confidence=0.8,
        business_criticality="low",
        evidence=["low cpu"],
        preconditions=["compute is present"],
        proposed_actions=["stop i-h5"],
        rollback_plan=["start i-h5"],
        success_metrics=["monthly cost at or below 0.00"],
        approval_status=approval_status,
        risk_assessment=RiskAssessment(
            risk_score=0.05,
            risk_class="SAFE_AUTOMATION",
            reasons=["development resource"],
        ),
    )
