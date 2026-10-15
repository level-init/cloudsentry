from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.proposals import ApprovalStatus, OptimizationProposal, RiskAssessment
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


def test_openapi_lists_proposal_routes() -> None:
    schema = create_app().openapi()
    parameters = schema["paths"]["/proposals"]["get"]["parameters"]
    names = {item["name"] for item in parameters}

    assert "/proposals" in schema["paths"]
    assert "/proposals/{proposal_id}" in schema["paths"]
    approve = schema["paths"]["/proposals/{proposal_id}/approve"]["post"]
    reject = schema["paths"]["/proposals/{proposal_id}/reject"]["post"]
    assert approve["tags"] == ["proposals"]
    assert reject["tags"] == ["proposals"]
    assert "X-Actor" in {item["name"] for item in approve["parameters"]}
    assert "X-Actor" in {item["name"] for item in reject["parameters"]}
    execute = schema["paths"]["/proposals/{proposal_id}/execute"]["post"]
    assert execute["tags"] == ["proposals"]
    audit = schema["paths"]["/proposals/{proposal_id}/audit"]
    assert set(audit) == {"get"}
    assert audit["get"]["tags"] == ["proposals"]
    assert {
        "status",
        "risk_class",
        "environment",
        "team",
        "category",
        "limit",
        "offset",
    } <= names
    assert schema["paths"]["/proposals"]["get"]["tags"] == ["proposals"]


def test_filters_return_the_matching_subset(session: Session) -> None:
    _seed(session)
    client = _client(session)

    pending = client.get("/proposals", params={"status": "pending", "team": "team-g9-payments"})
    production = client.get(
        "/proposals",
        params={"environment": "production", "team": "team-g9-payments"},
    )
    safe = client.get(
        "/proposals",
        params={"risk_class": "SAFE_AUTOMATION", "team": "team-g9-payments"},
    )
    idle = client.get(
        "/proposals",
        params={"category": "idle_compute", "team": "team-g9-payments"},
    )
    page = client.get(
        "/proposals",
        params={"team": "team-g9-payments", "limit": 1, "offset": 0},
    )
    second = client.get(
        "/proposals",
        params={"team": "team-g9-payments", "limit": 1, "offset": 1},
    )
    detail = client.get("/proposals/opt-g9-dev")
    missing = client.get("/proposals/opt-g9-missing")
    invalid = client.get("/proposals", params={"status": "nope"})

    assert _ids(pending) == ["opt-g9-dev"]
    assert pending.json()["total"] == 1
    assert _ids(production) == ["opt-g9-prod"]
    assert _ids(safe) == ["opt-g9-dev"]
    assert _ids(idle) == ["opt-g9-dev"]
    assert page.json()["total"] == 2
    assert page.json()["limit"] == 1
    assert page.json()["offset"] == 0
    assert _ids(page) == ["opt-g9-dev"]
    assert _ids(second) == ["opt-g9-prod"]
    assert detail.status_code == 200
    body = detail.json()
    assert body["proposal_id"] == "opt-g9-dev"
    assert body["category"] == "idle_compute"
    assert body["preconditions"] == ["compute is present"]
    assert body["execution_steps"] == ["stop i-g9-dev"]
    assert body["rollback"] == ["start i-g9-dev"]
    assert body["success_metrics"] == ["monthly cost at or below 0.00"]
    assert body["risk_assessment"]["risk_class"] == "SAFE_AUTOMATION"
    assert body["risk_assessment"]["risk_score"] == 0.05
    assert body["narrative"] is None
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_approve_and_reject_store_the_actor_and_reason(session: Session) -> None:
    _seed(session)
    client = _client(session)
    repository = ProposalRepository(session)

    approved = client.post(
        "/proposals/opt-g9-dev/approve",
        headers={"X-Actor": "ada"},
        json={"reason": "the idle instance can stop"},
    )
    rejected = client.post(
        "/proposals/opt-g9-other/reject",
        headers={"X-Actor": " ada "},
        json={"reason": " keep the schedule "},
    )
    missing = client.post(
        "/proposals/opt-g9-missing/approve",
        headers={"X-Actor": "ada"},
        json={"reason": "nothing to approve"},
    )
    no_actor = client.post(
        "/proposals/opt-g9-dev/approve",
        json={"reason": "the idle instance can stop"},
    )
    blank_actor = client.post(
        "/proposals/opt-g9-dev/approve",
        headers={"X-Actor": " "},
        json={"reason": "the idle instance can stop"},
    )
    blank_reason = client.post(
        "/proposals/opt-g9-dev/approve",
        headers={"X-Actor": "ada"},
        json={"reason": " "},
    )
    again = client.post(
        "/proposals/opt-g9-dev/approve",
        headers={"X-Actor": "ada"},
        json={"reason": "approve it once more"},
    )
    already = client.post(
        "/proposals/opt-g9-prod/reject",
        headers={"X-Actor": "ada"},
        json={"reason": "this one is already approved"},
    )

    assert approved.status_code == 200
    assert approved.json()["approval_status"] == "approved"
    assert approved.json()["proposal_id"] == "opt-g9-dev"
    approval = repository.decisions("opt-g9-dev")
    assert len(approval) == 1
    assert approval[0].actor == "ada"
    assert approval[0].reason == "the idle instance can stop"
    assert approval[0].from_status == ApprovalStatus.pending
    assert approval[0].to_status == ApprovalStatus.approved
    assert rejected.status_code == 200
    assert rejected.json()["approval_status"] == "rejected"
    refusal = repository.decisions("opt-g9-other")
    assert len(refusal) == 1
    assert refusal[0].actor == "ada"
    assert refusal[0].reason == "keep the schedule"
    assert refusal[0].to_status == ApprovalStatus.rejected
    assert missing.status_code == 404
    assert no_actor.status_code == 422
    assert blank_actor.status_code == 422
    assert blank_reason.status_code == 422
    assert again.status_code == 409
    assert "re-approve" in again.json()["detail"]
    assert already.status_code == 409
    assert repository.get("opt-g9-dev").approval_status == ApprovalStatus.approved
    assert repository.get("opt-g9-prod").approval_status == ApprovalStatus.approved


def test_execute_waits_for_approval(session: Session) -> None:
    _seed(session)
    client = _client(session)

    pending = client.post("/proposals/opt-g9-dev/execute")
    missing = client.post("/proposals/opt-g9-missing/execute")
    still_pending = client.get("/proposals/opt-g9-dev")
    approved = client.post(
        "/proposals/opt-g9-dev/approve",
        headers={"X-Actor": "ada"},
        json={"reason": "the idle instance can stop"},
    )
    queued = client.post("/proposals/opt-g9-dev/execute")
    again = client.post("/proposals/opt-g9-dev/execute")

    assert pending.status_code == 409
    assert "must be approved" in pending.json()["detail"]
    assert still_pending.json()["approval_status"] == "pending"
    assert still_pending.json()["execution_status"] == "not_started"
    assert missing.status_code == 404
    assert approved.status_code == 200
    assert queued.status_code == 200
    assert queued.json()["approval_status"] == "approved"
    assert queued.json()["execution_status"] == "queued"
    assert again.status_code == 200
    assert again.json()["execution_status"] == "queued"


def test_audit_lists_approve_and_reject_without_a_change_route(session: Session) -> None:
    _seed(session)
    client = _client(session)

    empty = client.get("/proposals/opt-g9-prod/audit")
    missing = client.get("/proposals/opt-g9-missing/audit")
    client.post(
        "/proposals/opt-g9-dev/approve",
        headers={"X-Actor": "ada"},
        json={"reason": "the idle instance can stop"},
    )
    client.post(
        "/proposals/opt-g9-other/reject",
        headers={"X-Actor": "ada"},
        json={"reason": "keep the schedule"},
    )
    approved = client.get("/proposals/opt-g9-dev/audit")
    rejected = client.get("/proposals/opt-g9-other/audit")
    updated = client.put(
        "/proposals/opt-g9-dev/audit",
        json={"reason": "tampered"},
    )
    deleted = client.delete("/proposals/opt-g9-dev/audit")

    assert empty.status_code == 200
    assert empty.json() == []
    assert missing.status_code == 404
    assert approved.status_code == 200
    assert len(approved.json()) == 1
    assert approved.json()[0]["actor"] == "ada"
    assert approved.json()[0]["reason"] == "the idle instance can stop"
    assert approved.json()[0]["from_status"] == "pending"
    assert approved.json()[0]["to_status"] == "approved"
    assert rejected.status_code == 200
    assert rejected.json()[0]["reason"] == "keep the schedule"
    assert rejected.json()[0]["to_status"] == "rejected"
    assert updated.status_code == 405
    assert deleted.status_code == 405


def _client(session: Session) -> TestClient:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def _ids(response) -> list[str]:
    assert response.status_code == 200
    return [item["proposal_id"] for item in response.json()["items"]]


def _seed(session: Session) -> None:
    resources = ResourceRepository(session)
    resources.create(_resource("i-g9-dev", "development", "team-g9-payments"))
    resources.create(_resource("i-g9-prod", "production", "team-g9-payments"))
    resources.create(_resource("i-g9-other", "development", "team-g9-platform"))
    _finding(session, "find-g9-dev", "i-g9-dev")
    _finding(session, "find-g9-prod", "i-g9-prod")
    _finding(session, "find-g9-other", "i-g9-other")
    proposals = ProposalRepository(session)
    proposals.create(
        _proposal(
            "opt-g9-dev",
            "find-g9-dev",
            "i-g9-dev",
            "pending",
            "SAFE_AUTOMATION",
            "idle_compute",
        )
    )
    proposals.create(
        _proposal(
            "opt-g9-prod",
            "find-g9-prod",
            "i-g9-prod",
            "approved",
            "ENGINEERING_REVIEW_REQUIRED",
            "compute_rightsizing",
        )
    )
    proposals.create(
        _proposal(
            "opt-g9-other",
            "find-g9-other",
            "i-g9-other",
            "pending",
            "APPROVAL_REQUIRED",
            "development_scheduling",
        )
    )


def _finding(session: Session, finding_id: str, resource_id: str) -> None:
    session.add(
        FindingRow(
            finding_id=finding_id,
            resource_ids=[resource_id],
            category="idle_compute",
            summary="planted for the proposal list",
            evidence=["low cpu"],
        )
    )
    session.flush()


def _resource(resource_id: str, environment: str, team: str) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id="111111111111",
        environment=environment,
        owner="payments-team",
        team=team,
        business_criticality="low",
        tags={"environment": environment},
    )


def _proposal(
    proposal_id: str,
    finding_id: str,
    resource_id: str,
    approval_status: str,
    risk_class: str,
    category: str,
) -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id=proposal_id,
        finding_id=finding_id,
        resource_ids=[resource_id],
        category=category,
        current_monthly_cost=30.37,
        predicted_monthly_cost=0,
        predicted_monthly_savings=30.37,
        confidence=0.8,
        business_criticality="low",
        evidence=["average CPU 3.7 percent"],
        preconditions=["compute is present"],
        proposed_actions=[f"stop {resource_id}"],
        rollback_plan=[f"start {resource_id}"],
        success_metrics=["monthly cost at or below 0.00"],
        approval_status=approval_status,
        risk_assessment=RiskAssessment(
            risk_score=0.05,
            risk_class=risk_class,
            reasons=["development resource"],
        ),
    )
