import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.proposals import ApprovalStatus, Finding, OptimizationProposal
from app.repositories import (
    CostRecordRepository,
    DependencyRepository,
    FindingRepository,
    ProposalRepository,
    ResourceRepository,
)
from app.schemas import CostRecord, Dependency, Resource
from worker.proposals import propose

_PRODUCT_FIELDS = {
    "proposal_id",
    "finding_id",
    "resource_ids",
    "category",
    "current_monthly_cost",
    "predicted_monthly_cost",
    "predicted_monthly_savings",
    "confidence",
    "business_criticality",
    "evidence",
    "dependencies",
    "preconditions",
    "proposed_actions",
    "rollback_plan",
    "success_metrics",
    "approval_status",
    "execution_status",
    "verification_status",
    "realized_savings",
    "risk_assessment",
}


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


def test_each_mvp_finding_becomes_a_proposal_and_a_second_run_skips_it(
    session: Session,
) -> None:
    _plant(session)
    finding_ids = {
        "idle_compute-i-prop-idle",
        "compute_rightsizing-i-prop-size",
        "development_scheduling-i-prop-sched",
        "unattached_storage-vol-prop-disk",
        "storage_lifecycle-bucket-prop",
        "storage_lifecycle-snap-prop",
        "sample-i-prop-sample",
    }

    first = propose(session)
    ours = [item for item in first.created if item.finding_id in finding_ids]
    by_finding = {item.finding_id: item for item in ours}

    assert set(by_finding) == finding_ids - {"sample-i-prop-sample"}
    assert all(item.finding_id not in finding_ids for item in first.skipped)
    _assert_idle(by_finding["idle_compute-i-prop-idle"])
    _assert_actions(by_finding)

    second = propose(session)
    assert all(item.finding_id not in finding_ids for item in second.created)
    assert finding_ids - {"sample-i-prop-sample"} <= {item.finding_id for item in second.skipped}

    idle_id = "proposal-idle_compute-i-prop-idle"
    ProposalRepository(session).update_status(
        idle_id,
        approval_status=ApprovalStatus.rejected,
        actor="tester",
        reason="reject the idle proposal so a new one can be created",
    )
    third = propose(session)
    reopened = [item for item in third.created if item.finding_id == "idle_compute-i-prop-idle"]
    assert [item.proposal_id for item in reopened] == [f"{idle_id}-2"]
    assert reopened[0].approval_status == ApprovalStatus.pending


def _assert_idle(proposal: OptimizationProposal) -> None:
    payload = json.loads(proposal.model_dump_json())

    assert _PRODUCT_FIELDS <= set(payload)
    assert payload["proposal_id"] == "proposal-idle_compute-i-prop-idle"
    assert payload["resource_ids"] == ["i-prop-idle"]
    assert payload["category"] == "idle_compute"
    assert payload["current_monthly_cost"] == 30.37
    assert payload["predicted_monthly_cost"] == 0.0
    assert payload["predicted_monthly_savings"] == 30.37
    assert payload["confidence"] == 0.8
    assert payload["business_criticality"] == "low"
    assert payload["dependencies"] == ["uses_database db-prop-idle"]
    assert payload["preconditions"] == [
        "compute is present",
        "cpu and request averages and peaks stay under the idle caps",
    ]
    assert payload["proposed_actions"] == ["stop i-prop-idle"]
    assert payload["execution_steps"] == ["stop i-prop-idle"]
    assert payload["rollback_plan"] == ["start i-prop-idle"]
    assert payload["rollback"] == ["start i-prop-idle"]
    assert payload["success_metrics"] == ["monthly cost at or below 0.00"]
    assert "success_metric monthly cost at or below 0.00" in payload["evidence"]
    assert payload["approval_status"] == "pending"
    assert payload["execution_status"] == "not_started"
    assert payload["verification_status"] == "not_started"
    assert payload["realized_savings"] is None
    assert payload["risk_assessment"]["risk_class"] == "SAFE_AUTOMATION"
    assert payload["risk_assessment"]["risk_score"] == 0.05
    assert "It depends on 1 resource" in payload["risk_assessment"]["reasons"]
    assert payload["risk_assessment"]["reasons"]


def _assert_actions(by_finding: dict[str, OptimizationProposal]) -> None:
    assert by_finding["compute_rightsizing-i-prop-size"].proposed_actions == [
        "resize i-prop-size to m5.large"
    ]
    assert by_finding["compute_rightsizing-i-prop-size"].rollback_plan == [
        "resize i-prop-size to m5.xlarge"
    ]
    assert by_finding["compute_rightsizing-i-prop-size"].predicted_monthly_cost == 70.08
    scheduling = by_finding["development_scheduling-i-prop-sched"]
    assert scheduling.proposed_actions == ["schedule i-prop-sched weekdays-09-17"]
    assert scheduling.rollback_plan == ["schedule i-prop-sched always_on"]
    assert scheduling.predicted_monthly_cost == 16.68
    disk = by_finding["unattached_storage-vol-prop-disk"]
    assert disk.proposed_actions == ["delete vol-prop-disk"]
    assert disk.predicted_monthly_cost == 0
    bucket = by_finding["storage_lifecycle-bucket-prop"]
    assert bucket.proposed_actions == ["transition bucket-prop to infrequent_access"]
    assert bucket.rollback_plan == ["transition bucket-prop to standard"]
    assert bucket.predicted_monthly_cost == 57.5
    snapshot = by_finding["storage_lifecycle-snap-prop"]
    assert snapshot.proposed_actions == ["expire snap-prop"]
    assert snapshot.predicted_monthly_cost == 0


def _plant(session: Session) -> None:
    resources = ResourceRepository(session)
    resources.upsert(_resource("i-prop-idle", "compute", "t3.medium"))
    resources.upsert(_resource("db-prop-idle", "database", None))
    resources.upsert(_resource("i-prop-size", "compute", "m5.xlarge"))
    resources.upsert(_resource("i-prop-sched", "compute", "m5.large"))
    resources.upsert(_resource("vol-prop-disk", "disk", "gp3-500gb"))
    resources.upsert(_resource("bucket-prop", "object_storage", "s3-standard-5tb", "standard"))
    resources.upsert(_resource("snap-prop", "snapshot", "snapshot-1tb"))
    resources.upsert(_resource("i-prop-sample", "compute", "t3.medium"))
    DependencyRepository(session).upsert_many(
        [
            Dependency(
                source_resource_id="i-prop-idle",
                target_resource_id="db-prop-idle",
                relationship="uses_database",
            )
        ]
    )
    costs = CostRecordRepository(session)
    costs.upsert_many(
        [
            _cost("i-prop-idle", 3037),
            _cost("i-prop-size", 14016),
            _cost("i-prop-sched", 7008),
            _cost("vol-prop-disk", 4000),
            _cost("bucket-prop", 11500),
            _cost("snap-prop", 5000),
        ]
    )
    findings = FindingRepository(session)
    findings.upsert(
        _finding(
            "idle_compute-i-prop-idle",
            "i-prop-idle",
            "idle_compute",
            ["cpu_percent avg 7.93"],
        )
    )
    findings.upsert(
        _finding(
            "compute_rightsizing-i-prop-size",
            "i-prop-size",
            "compute_rightsizing",
            ["current_sku m5.xlarge", "recommended_sku m5.large"],
        )
    )
    findings.upsert(
        _finding(
            "development_scheduling-i-prop-sched",
            "i-prop-sched",
            "development_scheduling",
            ["schedule weekdays-09-17"],
        )
    )
    findings.upsert(
        _finding(
            "unattached_storage-vol-prop-disk",
            "vol-prop-disk",
            "unattached_storage",
            ["monthly_cost_cents 4000", "resource_type disk"],
        )
    )
    findings.upsert(
        _finding(
            "storage_lifecycle-bucket-prop",
            "bucket-prop",
            "storage_lifecycle",
            ["monthly_cost_cents 11500", "action transition-to-infrequent-access"],
        )
    )
    findings.upsert(
        _finding(
            "storage_lifecycle-snap-prop",
            "snap-prop",
            "storage_lifecycle",
            ["monthly_cost_cents 5000", "action expire-after-90-days"],
        )
    )
    findings.upsert(
        _finding("sample-i-prop-sample", "i-prop-sample", "sample", ["tag scenario=sample"])
    )


def _resource(
    resource_id: str,
    resource_type: str,
    sku: str | None,
    storage_class: str | None = None,
) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type=resource_type,
        account_id="111111111111",
        environment="development",
        owner="payments",
        team="payments",
        business_criticality="low",
        tags={"environment": "development"},
        sku=sku,
        storage_class=storage_class,
    )


def _finding(finding_id: str, resource_id: str, category: str, evidence: list[str]) -> Finding:
    return Finding(
        finding_id=finding_id,
        resource_ids=[resource_id],
        category=category,
        summary=f"{resource_id} {category}",
        evidence=evidence,
    )


def _cost(resource_id: str, cents: int) -> CostRecord:
    start = datetime(2099, 4, 15, tzinfo=UTC)
    return CostRecord(
        resource_id=resource_id,
        period_start=start,
        period_end=start.replace(day=start.day + 1),
        amount=cents / 100,
        currency="USD",
    )
