from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import CostRecordRepository, DependencyRepository, ResourceRepository
from app.schemas import CostRecord, Dependency, Resource
from worker.detectors.storage import UnattachedStorageDetector


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


def test_unattached_disk_and_old_snapshot_are_found(session: Session) -> None:
    resources = ResourceRepository(session)
    disk = _resource("vol-dev-042", "disk", "development", {"scenario": "unattached_disk"})
    attached = _resource("vol-attached", "disk", "development", {})
    source = _resource("i-store-1", "compute", "development", {})
    snapshot = _resource(
        "snap-dev-007",
        "snapshot",
        "development",
        {"scenario": "expensive_snapshot"},
    )
    production = _resource("snap-prd-old", "snapshot", "production", {})
    young = _resource("vol-young", "disk", "development", {})
    for resource in (disk, attached, source, snapshot, production, young):
        resources.upsert(resource)
    DependencyRepository(session).upsert_many(
        [
            Dependency(
                source_resource_id="i-store-1",
                target_resource_id="vol-attached",
                relationship="stores_on",
            )
        ]
    )
    costs = CostRecordRepository(session)
    costs.upsert_many(_history("vol-dev-042", 4000))
    costs.upsert_many(_history("vol-attached", 800))
    costs.upsert_many(_history("snap-dev-007", 5000))
    costs.upsert_many(_history("snap-prd-old", 500))
    costs.upsert_many(
        [
            _line("vol-young", datetime(2099, 3, 1, tzinfo=UTC), 100),
            _line("vol-young", datetime(2099, 3, 10, tzinfo=UTC), 100),
        ]
    )

    findings = UnattachedStorageDetector().detect(
        [disk, attached, snapshot, production, young],
        session,
    )
    found = {finding.resource_ids[0]: finding for finding in findings}

    assert set(found) == {"vol-dev-042", "snap-dev-007"}
    evidence = " ".join(found["vol-dev-042"].evidence)
    assert "attach_state unattached" in evidence
    assert _age_days(found["vol-dev-042"].evidence) >= 30
    assert "monthly_cost_cents 4000" in evidence
    assert "scenario=unattached_disk" in evidence
    assert "attach_state unused" in " ".join(found["snap-dev-007"].evidence)
    assert "monthly_cost_cents 5000" in " ".join(found["snap-dev-007"].evidence)
    assert found["vol-dev-042"].category == "unattached_storage"


def _age_days(evidence: list[str]) -> int:
    line = next(item for item in evidence if item.startswith("age_days "))
    return int(line.removeprefix("age_days "))


def _resource(
    resource_id: str,
    resource_type: str,
    environment: str,
    tags: dict[str, str],
) -> Resource:
    stored_tags = {"environment": environment, "owner": "payments", "team": "payments"}
    stored_tags.update(tags)
    return Resource(
        resource_id=resource_id,
        resource_type=resource_type,
        account_id="111111111111",
        environment=environment,
        owner="payments",
        team="payments",
        business_criticality="low",
        tags=stored_tags,
    )


def _history(resource_id: str, march_cents: int) -> list[CostRecord]:
    return [
        _line(resource_id, datetime(2099, 1, 1, tzinfo=UTC), 100),
        _line(resource_id, datetime(2099, 3, 15, tzinfo=UTC), march_cents),
    ]


def _line(resource_id: str, start: datetime, cents: int) -> CostRecord:
    return CostRecord(
        resource_id=resource_id,
        period_start=start,
        period_end=start.replace(day=start.day + 1),
        amount=cents / 100,
        currency="USD",
    )
