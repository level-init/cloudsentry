from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.proposals import ApprovalStatus, ExecutionStatus, OptimizationProposal, RiskAssessment
from app.repositories import PolicyRepository, ProposalRepository, ResourceRepository
from app.schemas import Resource
from app.tables import FindingRow, PolicyRow


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


def _resource(
    resource_id: str,
    environment: str = "development",
    resource_type: str = "compute_instance",
) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type=resource_type,
        account_id="111111111111",
        environment=environment,
        owner="payments-team",
        team="payments",
        business_criticality="low",
        tags={"environment": environment},
    )


def _proposal(
    proposal_id: str,
    finding_id: str,
    approval_status: str = "pending",
    resource_ids: list[str] | None = None,
    proposed_actions: list[str] | None = None,
    category: str = "idle_compute",
) -> OptimizationProposal:
    return OptimizationProposal(
        proposal_id=proposal_id,
        finding_id=finding_id,
        resource_ids=["i-dev-1"] if resource_ids is None else resource_ids,
        category=category,
        current_monthly_cost=182.4,
        predicted_monthly_cost=0,
        predicted_monthly_savings=182.4,
        confidence=0.94,
        business_criticality="low",
        evidence=["average CPU 3.7 percent"],
        proposed_actions=["stop outside business hours"]
        if proposed_actions is None
        else proposed_actions,
        rollback_plan=["start the instance"],
        approval_status=approval_status,
        risk_assessment=RiskAssessment(
            risk_score=0.12,
            risk_class="APPROVAL_REQUIRED",
            reasons=["development resource"],
        ),
    )


def test_create_and_get_resource(session: Session) -> None:
    repository = ResourceRepository(session)
    created = repository.create(_resource("i-dev-1"))

    fetched = repository.get(created.resource_id)

    assert fetched is not None
    assert fetched.owner == "payments-team"
    assert fetched.tags["environment"] == "development"
    assert repository.get("missing") is None


def test_list_resources_filters_by_environment(session: Session) -> None:
    repository = ResourceRepository(session)
    repository.create(_resource("i-dev-1", "development"))
    repository.create(_resource("i-prod-1", "production"))

    development = repository.list(environment="development")
    ids = [resource.resource_id for resource in development]

    assert "i-dev-1" in ids
    assert "i-prod-1" not in ids
    assert all(resource.environment == "development" for resource in development)


def test_upsert_updates_the_same_resource_id(session: Session) -> None:
    repository = ResourceRepository(session)
    created = repository.upsert(_resource("i-dev-1"))
    changed = _resource("i-dev-1").model_copy(
        update={"owner": "platform", "tags": {"environment": "development"}}
    )
    updated = repository.upsert(changed)

    fetched = repository.get("i-dev-1")
    matches = [
        resource.resource_id for resource in repository.list() if resource.resource_id == "i-dev-1"
    ]

    assert created is True
    assert updated is False
    assert fetched is not None
    assert fetched.owner == "platform"
    assert matches == ["i-dev-1"]


def test_create_get_and_filter_proposals(session: Session) -> None:
    session.add(
        FindingRow(
            finding_id="find-1",
            resource_ids=["i-dev-1"],
            category="idle_compute",
            summary="idle development instance",
            evidence=["low cpu"],
        )
    )
    session.add(
        FindingRow(
            finding_id="find-2",
            resource_ids=["i-dev-1"],
            category="idle_compute",
            summary="second finding",
            evidence=["low network"],
        )
    )
    session.flush()
    repository = ProposalRepository(session)
    repository.create(_proposal("opt-1", "find-1", "pending"))
    repository.create(_proposal("opt-2", "find-2", "approved"))

    fetched = repository.get("opt-1")
    pending = repository.list(approval_status="pending")

    assert fetched is not None
    assert fetched.predicted_monthly_savings == 182.4
    assert fetched.risk_assessment.risk_class == "APPROVAL_REQUIRED"
    assert [proposal.proposal_id for proposal in pending] == ["opt-1"]
    assert repository.get("missing") is None


def test_update_proposal_status(session: Session) -> None:
    session.add(
        FindingRow(
            finding_id="find-1",
            resource_ids=["i-dev-1"],
            category="idle_compute",
            summary="idle development instance",
            evidence=["low cpu"],
        )
    )
    session.flush()
    repository = ProposalRepository(session)
    repository.create(_proposal("opt-1", "find-1"))

    updated = repository.update_status(
        "opt-1",
        approval_status=ApprovalStatus.approved,
        execution_status=ExecutionStatus.queued,
    )

    assert updated is not None
    assert updated.approval_status == "approved"
    assert updated.execution_status == "queued"
    assert updated.verification_status == "not_started"


def test_rejected_proposal_stays_out_of_execution_unless_a_policy_allows_it(
    session: Session,
) -> None:
    session.add(
        FindingRow(
            finding_id="find-rejected",
            resource_ids=["i-prd-017"],
            category="rightsizing_veto",
            summary="do not resize the spike trap",
            evidence=["projected peak 200"],
        )
    )
    session.flush()
    repository = ProposalRepository(session)
    created = _proposal("opt-rejected", "find-rejected")
    created.risk_assessment = RiskAssessment(
        risk_score=0.65,
        risk_class="REJECTED",
        reasons=["projected peak does not fit"],
    )
    repository.create(created)

    with pytest.raises(ValueError, match="cannot be approved"):
        repository.update_status("opt-rejected", approval_status=ApprovalStatus.approved)
    with pytest.raises(ValueError, match="cannot be approved"):
        repository.update_status("opt-rejected", execution_status=ExecutionStatus.queued)

    session.add(PolicyRow(name="override-rejected", effect="allow", actions=["approve_rejected"]))
    session.flush()
    updated = repository.update_status(
        "opt-rejected",
        approval_status=ApprovalStatus.approved,
        execution_status=ExecutionStatus.queued,
    )

    assert updated is not None
    assert updated.approval_status == "approved"
    assert updated.execution_status == "queued"


def test_seed_defaults_keeps_one_row_per_policy_name(session: Session) -> None:
    repository = PolicyRepository(session)
    repository.seed_defaults()
    repository.seed_defaults()

    names = [policy.name for policy in repository.list()]

    assert names.count("prohibit-delete-production-database") == 1
    assert names.count("require-approval-development-schedule") == 1
    assert names.count("allow-development-stop") == 1


def test_prohibit_delete_production_database_blocks_execution(session: Session) -> None:
    ResourceRepository(session).create(_resource("db-policy-prd", "production", "database"))
    session.add(
        FindingRow(
            finding_id="find-delete-db",
            resource_ids=["db-policy-prd"],
            category="unattached_storage",
            summary="delete a production database",
            evidence=["unused"],
        )
    )
    session.flush()
    PolicyRepository(session).seed_defaults()
    repository = ProposalRepository(session)
    repository.create(
        _proposal(
            "opt-delete-db",
            "find-delete-db",
            resource_ids=["db-policy-prd"],
            proposed_actions=["delete db-policy-prd"],
            category="unattached_storage",
        )
    )

    with pytest.raises(ValueError, match="prohibits"):
        repository.update_status("opt-delete-db", approval_status=ApprovalStatus.approved)
    with pytest.raises(ValueError, match="prohibits"):
        repository.update_status("opt-delete-db", execution_status=ExecutionStatus.queued)
    cancelled = repository.update_status("opt-delete-db", approval_status=ApprovalStatus.cancelled)

    assert cancelled is not None
    assert cancelled.approval_status == "cancelled"


def test_development_schedule_stays_approvable(session: Session) -> None:
    ResourceRepository(session).create(_resource("i-policy-dev", "development", "compute"))
    session.add(
        FindingRow(
            finding_id="find-schedule",
            resource_ids=["i-policy-dev"],
            category="development_scheduling",
            summary="schedule a development instance",
            evidence=["weekend cpu"],
        )
    )
    session.flush()
    PolicyRepository(session).seed_defaults()
    repository = ProposalRepository(session)
    repository.create(
        _proposal(
            "opt-schedule",
            "find-schedule",
            resource_ids=["i-policy-dev"],
            proposed_actions=["schedule i-policy-dev weekdays-09-17"],
            category="development_scheduling",
        )
    )

    updated = repository.update_status("opt-schedule", approval_status=ApprovalStatus.approved)

    assert updated is not None
    assert updated.approval_status == "approved"
    assert updated.execution_status == "not_started"
