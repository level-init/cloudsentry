from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.proposals import ApprovalStatus, RiskClass
from app.repositories import (
    CostRecordRepository,
    FindingRepository,
    MetricRollupRepository,
    ResourceRepository,
)
from app.schemas import CostRecord, MetricRollup, Resource
from worker.detectors.rightsizing import projected_peak, veto_sku
from worker.detectors.veto import RightsizingVetoDetector
from worker.proposals import propose

_START = date(2099, 3, 2)


def test_spike_trap_peak_rejects_the_next_sku_and_the_two_step_drop() -> None:
    assert veto_sku("m5.xlarge", 7.36, 100.0, headroom=0.5, avg_max=15) == "m5.large"
    assert veto_sku("m5.xlarge", 7.98, 11.89, headroom=0.5, avg_max=15) is None
    assert veto_sku("t3.medium", 7.93, 11.95, headroom=0.5, avg_max=15) is None
    assert projected_peak("m5.xlarge", "m5.large", 100.0) == 200
    assert projected_peak("m5.xlarge", "t3.medium", 100.0) == 400


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


def test_detection_and_plan_reject_the_spike_trap_downsize(session: Session) -> None:
    spike = _resource("i-prd-017", "m5.xlarge", "production")
    oversized = _resource("i-prd-013", "m5.xlarge", "production")
    smallest = _resource("i-dev-062", "t3.medium", "development")
    resources = ResourceRepository(session)
    for resource in (spike, oversized, smallest):
        resources.upsert(resource)
    rollups = MetricRollupRepository(session)
    rollups.upsert_many(_series("i-prd-017", 7.36, 100.0))
    rollups.upsert_many(_series("i-prd-013", 7.98, 11.89))
    rollups.upsert_many(_series("i-dev-062", 7.93, 11.95))
    CostRecordRepository(session).upsert_many([_cost("i-prd-017", 14016)])

    findings = RightsizingVetoDetector().detect([spike, oversized, smallest], session)
    assert [finding.resource_ids[0] for finding in findings] == ["i-prd-017"]
    FindingRepository(session).upsert(findings[0])

    created = [
        proposal
        for proposal in propose(session).created
        if proposal.finding_id == "rightsizing_veto-i-prd-017"
    ]
    assert len(created) == 1
    proposal = created[0]
    assert proposal.risk_assessment.risk_class == RiskClass.rejected
    assert proposal.approval_status == ApprovalStatus.rejected
    assert proposal.proposed_actions == ["reject resize of i-prd-017 to m5.large"]
    assert "t3.medium" not in proposal.proposed_actions[0]
    assert not proposal.proposed_actions[0].startswith("resize ")
    assert proposal.predicted_monthly_savings == 0
    assert proposal.rollback_plan == ["keep i-prd-017 at m5.xlarge"]
    assert any("200" in reason for reason in proposal.risk_assessment.reasons)
    assert any("400" in reason for reason in proposal.risk_assessment.reasons)

    again = propose(session)
    assert all(item.finding_id != "rightsizing_veto-i-prd-017" for item in again.created)


def _resource(resource_id: str, sku: str, environment: str) -> Resource:
    account = "111111111111" if environment == "development" else "333333333333"
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id=account,
        environment=environment,
        owner="payments",
        team="payments",
        business_criticality="medium",
        tags={"scenario": "spike_trap"} if resource_id == "i-prd-017" else {},
        sku=sku,
    )


def _series(resource_id: str, average: float, peak: float) -> list[MetricRollup]:
    return [
        MetricRollup(
            resource_id=resource_id,
            name="cpu_percent",
            day=_START + timedelta(days=offset),
            avg_value=average,
            peak_value=peak,
            unit="percent",
        )
        for offset in range(30)
    ]


def _cost(resource_id: str, cents: int) -> CostRecord:
    start = datetime(2099, 4, 15, tzinfo=UTC)
    return CostRecord(
        resource_id=resource_id,
        period_start=start,
        period_end=start.replace(day=start.day + 1),
        amount=cents / 100,
        currency="USD",
    )
