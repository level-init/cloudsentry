from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import MetricRollupRepository, ResourceRepository
from app.schemas import MetricRollup, Resource
from worker.detectors.scheduling import SchedulingDetector

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


def test_always_on_dev_gets_a_weekday_schedule_and_production_does_not(
    session: Session,
) -> None:
    resources = ResourceRepository(session)
    always_on = _resource("i-dev-026", "development", {"scenario": "always_on_dev"})
    staging = _resource("i-stg-always", "staging", {})
    quiet = _resource("i-dev-quiet", "development", {})
    production = _resource("i-prd-always", "production", {})
    tag_blocks = _resource(
        "i-dev-tagged-prod",
        "development",
        {"environment": "production"},
    )
    for resource in (always_on, staging, quiet, production, tag_blocks):
        resources.upsert(resource)
    rollups = MetricRollupRepository(session)
    rollups.upsert_many(_series("i-dev-026", weekday=42.0, weekend=42.0))
    rollups.upsert_many(_series("i-stg-always", weekday=42.0, weekend=42.0))
    rollups.upsert_many(_series("i-dev-quiet", weekday=42.0, weekend=6.0))
    rollups.upsert_many(_series("i-prd-always", weekday=42.0, weekend=42.0))
    rollups.upsert_many(_series("i-dev-tagged-prod", weekday=42.0, weekend=42.0))

    findings = SchedulingDetector().detect(
        [always_on, staging, quiet, production, tag_blocks],
        session,
    )
    found = {finding.resource_ids[0]: finding for finding in findings}

    assert set(found) == {"i-dev-026", "i-stg-always"}
    evidence = " ".join(found["i-dev-026"].evidence)
    assert "environment development" in evidence
    assert "weekend_cpu_avg 42.00" in evidence
    assert "schedule weekdays-09-17" in evidence
    assert "window weekdays 09:00-17:00 UTC" in evidence
    assert "scenario=always_on_dev" in evidence
    assert found["i-dev-026"].category == "development_scheduling"
    assert "environment staging" in " ".join(found["i-stg-always"].evidence)


def _resource(resource_id: str, environment: str, tags: dict[str, str]) -> Resource:
    stored_tags = {"environment": environment, "team": "payments", "owner": "payments"}
    stored_tags.update(tags)
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id="111111111111",
        environment=environment,
        owner="payments",
        team="payments",
        business_criticality="low",
        tags=stored_tags,
    )


def _series(resource_id: str, *, weekday: float, weekend: float) -> list[MetricRollup]:
    rollups: list[MetricRollup] = []
    for offset in range(30):
        day = _START + timedelta(days=offset)
        rollups.append(
            MetricRollup(
                resource_id=resource_id,
                name="cpu_percent",
                day=day,
                avg_value=weekend if day.weekday() >= 5 else weekday,
                peak_value=weekend if day.weekday() >= 5 else weekday,
                unit="percent",
            )
        )
    return rollups
