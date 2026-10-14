"""Precision of the five detectors on the seeded waste fixtures.

Resource ids are the ones in simulator/DEMO_SCENARIOS.md. The detectors do not
read the scenario tag. i-prd-017 is the spike-trap: its average looks idle and
rightsizable, and its peak vetoes both. i-prd-005 looks idle too, and it is
not a named fixture. Incident inc-prd-idle does not suppress that finding.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.proposals import Finding
from app.repositories import CostRecordRepository, MetricRollupRepository, ResourceRepository
from app.schemas import CostRecord, MetricRollup, Resource
from worker.detectors.idle import IdleComputeDetector
from worker.detectors.lifecycle import LifecycleDetector
from worker.detectors.rightsizing import RightsizingDetector, next_sku
from worker.detectors.scheduling import SchedulingDetector
from worker.detectors.storage import UnattachedStorageDetector

# simulator/DEMO_SCENARIOS.md
_DEMO_IDS = (
    "i-dev-062",
    "i-dev-026",
    "i-prd-013",
    "vol-dev-042",
    "bucket-prd-022",
    "snap-dev-007",
    "i-prd-017",
)
_SOFT_IDLE = "i-prd-005"
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


def test_demo_scenario_ids_match_each_detector(session: Session) -> None:
    resources = _plant(session)

    idle = _by_id(IdleComputeDetector().detect(resources, session))
    rightsizing = _by_id(RightsizingDetector().detect(resources, session))
    scheduling = _by_id(SchedulingDetector().detect(resources, session))
    unattached = _by_id(UnattachedStorageDetector().detect(resources, session))
    lifecycle = _by_id(LifecycleDetector().detect(resources, session))

    assert set(idle) == {"i-dev-062", "i-prd-013", _SOFT_IDLE}
    assert set(rightsizing) == {"i-prd-013", _SOFT_IDLE}
    assert set(scheduling) == {"i-dev-026"}
    assert set(unattached) == {"vol-dev-042", "snap-dev-007"}
    assert set(lifecycle) == {"bucket-prd-022", "snap-dev-007"}
    assert _SOFT_IDLE not in _DEMO_IDS

    oversized = " ".join(rightsizing["i-prd-013"].evidence)
    assert "current_sku m5.xlarge" in oversized
    assert "recommended_sku m5.large" in oversized
    assert "t3.medium" not in oversized
    soft = " ".join(rightsizing[_SOFT_IDLE].evidence)
    assert "recommended_sku t3.medium" in soft
    assert "scenario=idle_compute" in " ".join(idle["i-dev-062"].evidence)
    assert "scenario=always_on_dev" in " ".join(scheduling["i-dev-026"].evidence)
    assert "scenario=unattached_disk" in " ".join(unattached["vol-dev-042"].evidence)
    bucket = " ".join(lifecycle["bucket-prd-022"].evidence)
    assert "current_tier standard" in bucket
    assert "access_proxy requests_avg 63.00" in bucket
    assert "action transition-to-infrequent-access" in bucket
    snapshot = " ".join(lifecycle["snap-dev-007"].evidence)
    assert "action expire-after-90-days" in snapshot
    assert idle["i-dev-062"].category == "idle_compute"
    assert rightsizing["i-prd-013"].category == "compute_rightsizing"
    assert scheduling["i-dev-026"].category == "development_scheduling"
    assert unattached["vol-dev-042"].category == "unattached_storage"
    assert lifecycle["bucket-prd-022"].category == "storage_lifecycle"


def test_spike_trap_average_would_pass_and_the_peak_vetoes_it(session: Session) -> None:
    resources = _plant(session)
    spike_avg = 7.36
    spike_peak = 100.0

    idle = _by_id(IdleComputeDetector().detect(resources, session))
    rightsizing = _by_id(RightsizingDetector().detect(resources, session))
    scheduling = _by_id(SchedulingDetector().detect(resources, session))

    assert spike_avg < 15
    assert next_sku("m5.xlarge", spike_avg, spike_peak, headroom=0.5, avg_max=15) is None
    assert "i-prd-017" not in idle
    assert "i-prd-017" not in rightsizing
    assert "i-prd-017" not in scheduling


def _plant(session: Session) -> list[Resource]:
    resources = [
        _compute(
            "i-dev-062", "development", "t3.medium", 7.93, 11.95, 11.90, 17.93, "idle_compute"
        ),
        _compute("i-dev-026", "development", "m5.large", 42.0, 50.0, 63.0, 75.0, "always_on_dev"),
        _compute(
            "i-prd-013", "production", "m5.xlarge", 7.98, 11.89, 11.96, 17.83, "oversized_compute"
        ),
        _compute("i-prd-017", "production", "m5.xlarge", 7.36, 100.0, 11.03, 150.0, "spike_trap"),
        _compute(_SOFT_IDLE, "production", "m5.large", 7.96, 11.89, 11.96, 17.83, None),
        _storage("vol-dev-042", "disk", "development", "gp3-500gb", None, 4000, "unattached_disk"),
        _storage(
            "bucket-prd-022",
            "object_storage",
            "production",
            "s3-standard-5tb",
            "standard",
            11500,
            "expensive_storage",
        ),
        _storage(
            "snap-dev-007",
            "snapshot",
            "development",
            "snapshot-1tb",
            None,
            5000,
            "expensive_snapshot",
        ),
    ]
    repository = ResourceRepository(session)
    rollups = MetricRollupRepository(session)
    costs = CostRecordRepository(session)
    for resource in resources:
        repository.upsert(resource)
        if resource.resource_type == "compute":
            rollups.upsert_many(_cpu(resource))
        if resource.resource_type in {"compute", "object_storage"}:
            rollups.upsert_many(_requests(resource))
        if resource.resource_type in {"disk", "snapshot", "object_storage"}:
            costs.upsert_many(_history(resource.resource_id, int(resource.tags["monthly_cents"])))
    return resources


def _by_id(findings: list[Finding]) -> dict[str, Finding]:
    return {finding.resource_ids[0]: finding for finding in findings}


def _compute(
    resource_id: str,
    environment: str,
    sku: str,
    cpu_avg: float,
    cpu_peak: float,
    request_avg: float,
    request_peak: float,
    scenario: str | None,
) -> Resource:
    resource = _resource(resource_id, "compute", environment, sku, None, scenario)
    resource.tags["cpu_avg"] = str(cpu_avg)
    resource.tags["cpu_peak"] = str(cpu_peak)
    resource.tags["request_avg"] = str(request_avg)
    resource.tags["request_peak"] = str(request_peak)
    return resource


def _storage(
    resource_id: str,
    resource_type: str,
    environment: str,
    sku: str,
    storage_class: str | None,
    monthly_cents: int,
    scenario: str,
) -> Resource:
    resource = _resource(resource_id, resource_type, environment, sku, storage_class, scenario)
    resource.tags["monthly_cents"] = str(monthly_cents)
    if resource_type == "object_storage":
        resource.tags["request_avg"] = "63.0"
        resource.tags["request_peak"] = "90.0"
    return resource


def _resource(
    resource_id: str,
    resource_type: str,
    environment: str,
    sku: str,
    storage_class: str | None,
    scenario: str | None,
) -> Resource:
    account_id = "111111111111" if environment == "development" else "333333333333"
    tags = {"environment": environment, "owner": "payments", "team": "payments"}
    if scenario is not None:
        tags["scenario"] = scenario
    return Resource(
        resource_id=resource_id,
        resource_type=resource_type,
        account_id=account_id,
        environment=environment,
        owner="payments",
        team="payments",
        business_criticality="low",
        tags=tags,
        sku=sku,
        storage_class=storage_class,
    )


def _cpu(resource: Resource) -> list[MetricRollup]:
    return _series(
        resource.resource_id,
        "cpu_percent",
        float(resource.tags["cpu_avg"]),
        float(resource.tags["cpu_peak"]),
        "percent",
    )


def _requests(resource: Resource) -> list[MetricRollup]:
    return _series(
        resource.resource_id,
        "requests",
        float(resource.tags["request_avg"]),
        float(resource.tags["request_peak"]),
        "count",
    )


def _series(
    resource_id: str,
    name: str,
    average: float,
    peak: float,
    unit: str,
) -> list[MetricRollup]:
    return [
        MetricRollup(
            resource_id=resource_id,
            name=name,
            day=_START + timedelta(days=offset),
            avg_value=average,
            peak_value=peak,
            unit=unit,
        )
        for offset in range(30)
    ]


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
