from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import MetricRollupRepository, ResourceRepository
from app.schemas import MetricRollup, Resource
from worker.detectors.rightsizing import RightsizingDetector, next_sku

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


def test_one_step_down_fits_the_oversized_vm_and_not_the_spike_trap() -> None:
    assert next_sku("m5.xlarge", 7.98, 11.89, headroom=0.5, avg_max=15) == "m5.large"
    assert next_sku("m5.xlarge", 7.36, 100.0, headroom=0.5, avg_max=15) is None
    assert next_sku("m5.xlarge", 1.0, 1.0, headroom=0.5, avg_max=15) == "m5.large"
    assert next_sku("t3.medium", 1.0, 1.0, headroom=0.5, avg_max=15) is None


def test_rightsizing_finds_the_oversized_fixture_and_skips_the_spike_trap(
    session: Session,
) -> None:
    resources = ResourceRepository(session)
    oversized = _resource("i-prd-013", "m5.xlarge", {"scenario": "oversized_compute"})
    spike = _resource("i-prd-017", "m5.xlarge", {"scenario": "spike_trap"})
    busy = _resource("i-dev-026", "m5.large", {"scenario": "always_on_dev"})
    smallest = _resource("i-dev-062", "t3.medium", {"scenario": "idle_compute"})
    for resource in (oversized, spike, busy, smallest):
        resources.upsert(resource)
    rollups = MetricRollupRepository(session)
    rollups.upsert_many(_series("i-prd-013", avg=7.98, peak=11.89))
    rollups.upsert_many(_series("i-prd-017", avg=7.36, peak=100.0))
    rollups.upsert_many(_series("i-dev-026", avg=42.03, peak=49.92))
    rollups.upsert_many(_series("i-dev-062", avg=7.93, peak=11.95))

    findings = RightsizingDetector().detect([oversized, spike, busy, smallest], session)
    found = {finding.resource_ids[0]: finding for finding in findings}

    assert set(found) == {"i-prd-013"}
    evidence = " ".join(found["i-prd-013"].evidence)
    assert "current_sku m5.xlarge" in evidence
    assert "recommended_sku m5.large" in evidence
    assert "t3.medium" not in evidence
    assert "projected_peak 23.78" in evidence
    assert found["i-prd-013"].category == "compute_rightsizing"


def _resource(resource_id: str, sku: str, tags: dict[str, str]) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id="333333333333",
        environment="production",
        owner="payments",
        team="payments",
        business_criticality="high",
        tags=tags,
        sku=sku,
    )


def _series(resource_id: str, *, avg: float, peak: float) -> list[MetricRollup]:
    return [
        MetricRollup(
            resource_id=resource_id,
            name="cpu_percent",
            day=_START + timedelta(days=offset),
            avg_value=avg,
            peak_value=peak,
            unit="percent",
        )
        for offset in range(30)
    ]
