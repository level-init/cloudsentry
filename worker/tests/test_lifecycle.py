from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import CostRecordRepository, MetricRollupRepository, ResourceRepository
from app.schemas import CostRecord, MetricRollup, Resource
from worker.detectors.lifecycle import LifecycleDetector

_START = date(2099, 3, 2)


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


def test_planted_bucket_and_snapshot_get_lifecycle_actions(session: Session) -> None:
    resources = ResourceRepository(session)
    bucket = _resource(
        "bucket-prd-022",
        "object_storage",
        "production",
        sku="s3-standard-5tb",
        storage_class="standard",
        tags={"scenario": "expensive_storage"},
    )
    small = _resource(
        "bucket-small",
        "object_storage",
        "production",
        sku="s3-standard-500gb",
        storage_class="standard",
        tags={},
    )
    cold = _resource(
        "bucket-cold",
        "object_storage",
        "production",
        sku="s3-standard-5tb",
        storage_class="infrequent_access",
        tags={},
    )
    snapshot = _resource(
        "snap-dev-007",
        "snapshot",
        "development",
        sku="snapshot-1tb",
        storage_class=None,
        tags={"scenario": "expensive_snapshot"},
    )
    production = _resource(
        "snap-prd-old",
        "snapshot",
        "production",
        sku="snapshot-1tb",
        storage_class=None,
        tags={},
    )
    for resource in (bucket, small, cold, snapshot, production):
        resources.upsert(resource)
    costs = CostRecordRepository(session)
    costs.upsert_many(_history("bucket-prd-022", 11500))
    costs.upsert_many(_history("bucket-small", 1150))
    costs.upsert_many(_history("bucket-cold", 5750))
    costs.upsert_many(_history("snap-dev-007", 5000))
    costs.upsert_many(_history("snap-prd-old", 5000))
    MetricRollupRepository(session).upsert_many(
        [
            MetricRollup(
                resource_id="bucket-prd-022",
                name="requests",
                day=_START + timedelta(days=offset),
                avg_value=12.0,
                peak_value=18.0,
                unit="count",
            )
            for offset in range(30)
        ]
    )

    findings = LifecycleDetector().detect([bucket, small, cold, snapshot, production], session)
    found = {finding.resource_ids[0]: finding for finding in findings}

    assert set(found) == {"bucket-prd-022", "snap-dev-007"}
    bucket_evidence = " ".join(found["bucket-prd-022"].evidence)
    assert "current_tier standard" in bucket_evidence
    assert "access_proxy requests_avg 12.00" in bucket_evidence
    assert "monthly_cost_cents 11500" in bucket_evidence
    assert "action transition-to-infrequent-access" in bucket_evidence
    assert "scenario=expensive_storage" in bucket_evidence
    snapshot_evidence = " ".join(found["snap-dev-007"].evidence)
    assert "current_tier snapshot-1tb" in snapshot_evidence
    assert "access_proxy unused" in snapshot_evidence
    assert "monthly_cost_cents 5000" in snapshot_evidence
    assert "action expire-after-90-days" in snapshot_evidence
    assert found["bucket-prd-022"].category == "storage_lifecycle"


def _resource(
    resource_id: str,
    resource_type: str,
    environment: str,
    *,
    sku: str,
    storage_class: str | None,
    tags: dict[str, str],
) -> Resource:
    stored_tags = {"environment": environment, "owner": "payments", "team": "payments"}
    stored_tags.update(tags)
    return Resource(
        resource_id=resource_id,
        resource_type=resource_type,
        account_id="333333333333",
        environment=environment,
        owner="payments",
        team="payments",
        business_criticality="low",
        tags=stored_tags,
        sku=sku,
        storage_class=storage_class,
    )


def _history(resource_id: str, latest_cents: int) -> list[CostRecord]:
    return [
        _line(resource_id, datetime(2099, 1, 1, tzinfo=UTC), 100),
        _line(resource_id, datetime(2099, 4, 15, tzinfo=UTC), latest_cents),
    ]


def _line(resource_id: str, start: datetime, cents: int) -> CostRecord:
    return CostRecord(
        resource_id=resource_id,
        period_start=start,
        period_end=start.replace(day=start.day + 1),
        amount=cents / 100,
        currency="USD",
    )
