from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import (
    CostRecordRepository,
    DependencyRepository,
    IncidentRepository,
    MetricRollupRepository,
    ResourceRepository,
)
from app.schemas import CostRecord, Dependency, Incident, MetricRollup, Resource
from app.tables import CostRecordRow, DependencyRow, IncidentRow, MetricRollupRow, ResourceRow
from worker.inventory import ingest_resources


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


def test_second_sync_keeps_counts_and_marks_removed_resources(session: Session) -> None:
    kept = _resource("i-sync-kept")
    gone = _resource("i-sync-gone")
    first = ingest_resources(session, [kept, gone])
    rollup = MetricRollup(
        resource_id="i-sync-gone",
        name="cpu_percent",
        day=date(2026, 3, 1),
        avg_value=4.0,
        peak_value=9.0,
        unit="percent",
    )
    cost = CostRecord(
        resource_id="i-sync-gone",
        period_start=datetime(2026, 3, 1, tzinfo=UTC),
        period_end=datetime(2026, 3, 2, tzinfo=UTC),
        amount=1.5,
        currency="USD",
    )
    edge = Dependency(
        source_resource_id="i-sync-kept",
        target_resource_id="i-sync-gone",
        relationship="uses_database",
    )
    incident = Incident(
        incident_id="inc-sync-1",
        resource_id="i-sync-gone",
        severity="low",
        started_at=datetime(2026, 3, 20, tzinfo=UTC),
        summary="idle",
    )
    rollups = MetricRollupRepository(session)
    costs = CostRecordRepository(session)
    dependencies = DependencyRepository(session)
    incidents = IncidentRepository(session)
    assert rollups.upsert_many([rollup])[0] == 1
    assert costs.upsert_many([cost])[0] == 1
    assert dependencies.upsert_many([edge])[0] == 1
    assert incidents.upsert_many([incident])[0] == 1
    before = _counts(session)

    second = ingest_resources(session, [kept, gone])
    assert rollups.upsert_many([rollup]) == (0, 1)
    assert costs.upsert_many([cost]) == (0, 1)
    assert dependencies.upsert_many([edge]) == (0, 1)
    assert incidents.upsert_many([incident]) == (0, 1)

    assert first.created == 2
    assert second.created == 0
    assert second.updated == 2
    assert _counts(session) == before

    removed = ingest_resources(session, [kept])
    stored_gone = ResourceRepository(session).get("i-sync-gone")
    stored_kept = ResourceRepository(session).get("i-sync-kept")
    assert stored_gone is not None
    assert stored_gone.present is False
    assert stored_kept is not None
    assert stored_kept.present is True
    assert removed.absent >= 1
    assert _counts(session) == before

    restored = ingest_resources(session, [kept, gone])
    assert ResourceRepository(session).get("i-sync-gone").present is True
    assert restored.created == 0
    assert _counts(session) == before


def _resource(resource_id: str) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id="111111111111",
        environment="development",
        owner="payments",
        team="payments",
        business_criticality="low",
    )


def _counts(session: Session) -> tuple[int, int, int, int, int]:
    ids = ("i-sync-kept", "i-sync-gone")
    return (
        _count(session, ResourceRow, ResourceRow.resource_id.in_(ids)),
        _count(session, MetricRollupRow, MetricRollupRow.resource_id == "i-sync-gone"),
        _count(session, CostRecordRow, CostRecordRow.resource_id == "i-sync-gone"),
        _count(
            session,
            DependencyRow,
            DependencyRow.source_resource_id == "i-sync-kept",
        ),
        _count(session, IncidentRow, IncidentRow.incident_id == "inc-sync-1"),
    )


def _count(session: Session, table: type, criterion) -> int:
    return int(session.scalar(select(func.count()).select_from(table).where(criterion)))
