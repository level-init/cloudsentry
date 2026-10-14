from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import MetricRollupRepository, ResourceRepository
from app.schemas import MetricRollup, Resource
from worker.detectors.idle import IdleComputeDetector

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


def test_idle_detector_finds_the_planted_idle_vm_and_skips_the_spike_trap(
    session: Session,
) -> None:
    resources = ResourceRepository(session)
    idle = _resource(
        "i-dev-062",
        "compute",
        {"scenario": "idle_compute", "owner": "payments-oncall"},
    )
    spike = _resource(
        "i-prd-017",
        "compute",
        {"scenario": "spike_trap", "owner": "data-oncall"},
    )
    busy = _resource("i-dev-026", "compute", {"scenario": "always_on_dev"})
    disk = _resource("vol-idle-1", "disk", {"scenario": "idle_compute"})
    short = _resource("i-idle-short", "compute", {"scenario": "idle_compute"})
    for resource in (idle, spike, busy, disk, short):
        resources.upsert(resource)
    rollups = MetricRollupRepository(session)
    rollups.upsert_many(
        _series("i-dev-062", cpu_avg=7.93, cpu_peak=11.95, request_avg=11.90, request_peak=17.93)
    )
    rollups.upsert_many(
        _series("i-prd-017", cpu_avg=7.36, cpu_peak=100.0, request_avg=11.03, request_peak=150.0)
    )
    rollups.upsert_many(
        _series("i-dev-026", cpu_avg=42.03, cpu_peak=49.92, request_avg=63.05, request_peak=74.88)
    )
    rollups.upsert_many(
        _series("vol-idle-1", cpu_avg=1.0, cpu_peak=1.0, request_avg=1.0, request_peak=1.0)
    )
    rollups.upsert_many(
        _series("i-idle-short", cpu_avg=1.0, cpu_peak=1.0, request_avg=1.0, request_peak=1.0)[:10]
    )

    findings = IdleComputeDetector().detect([idle, spike, busy, disk, short], session)
    found = {finding.resource_ids[0]: finding for finding in findings}

    assert "i-dev-062" in found
    assert "i-prd-017" not in found
    assert "i-dev-026" not in found
    assert "vol-idle-1" not in found
    assert "i-idle-short" not in found
    evidence = " ".join(found["i-dev-062"].evidence)
    assert "cpu_percent avg 7.93" in evidence
    assert "cpu_percent peak 11.95" in evidence
    assert "requests avg 11.90" in evidence
    assert "requests peak 17.93" in evidence
    assert "scenario=idle_compute" in evidence
    assert found["i-dev-062"].category == "idle_compute"


def _resource(resource_id: str, resource_type: str, tags: dict[str, str]) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type=resource_type,
        account_id="111111111111",
        environment="development",
        owner="payments",
        team="payments",
        business_criticality="low",
        tags=tags,
    )


def _series(
    resource_id: str,
    *,
    cpu_avg: float,
    cpu_peak: float,
    request_avg: float,
    request_peak: float,
) -> list[MetricRollup]:
    rollups: list[MetricRollup] = []
    for offset in range(30):
        day = _START + timedelta(days=offset)
        rollups.append(
            MetricRollup(
                resource_id=resource_id,
                name="cpu_percent",
                day=day,
                avg_value=cpu_avg,
                peak_value=cpu_peak,
                unit="percent",
            )
        )
        rollups.append(
            MetricRollup(
                resource_id=resource_id,
                name="requests",
                day=day,
                avg_value=request_avg,
                peak_value=request_peak,
                unit="count",
            )
        )
    return rollups
