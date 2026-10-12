from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import MetricRollupRepository, ResourceRepository
from app.schemas import MetricRollup, Resource


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


def test_thirty_day_cpu_average_and_peak_are_queryable(session: Session) -> None:
    ResourceRepository(session).create(
        Resource(
            resource_id="i-rollup-1",
            resource_type="compute",
            account_id="111111111111",
            environment="development",
            owner="payments",
            team="payments",
            business_criticality="low",
            tags={"criticality": "low"},
        )
    )
    start = date(2026, 3, 2)
    rollups = [
        MetricRollup(
            resource_id="i-rollup-1",
            name="cpu_percent",
            day=start + timedelta(days=offset),
            avg_value=8.0,
            peak_value=40.0 if offset == 10 else 9.0,
            unit="percent",
        )
        for offset in range(30)
    ]
    repository = MetricRollupRepository(session)
    created, updated = repository.upsert_many(rollups)
    average, peak = repository.summarize(
        "i-rollup-1",
        "cpu_percent",
        start,
        date(2026, 4, 1),
    )
    again_created, again_updated = repository.upsert_many(rollups)

    assert created == 30 and updated == 0
    assert average == 8.0
    assert peak == 40.0
    assert again_created == 0 and again_updated == 30
    assert repository.count("i-rollup-1", "cpu_percent") == 30
