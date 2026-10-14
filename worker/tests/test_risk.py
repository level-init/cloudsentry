from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.proposals import RiskClass
from app.repositories import (
    DependencyRepository,
    IncidentRepository,
    MetricRollupRepository,
    ResourceRepository,
)
from app.schemas import Dependency, Incident, MetricRollup, Resource
from worker.risk import RiskInputs, assess, score_risk

# Shapes from simulator/DEMO_SCENARIOS.md: i-dev-062 and i-prd-017.
_DEV_IDLE = RiskInputs("development", "low", 11.95, 2, 0, ())
_SPIKE = RiskInputs("production", "medium", 100.0, 2, 0, ())
_PROD_INCIDENT = RiskInputs("production", "high", 11.93, 2, 1, ("high",))


def test_dev_idle_scores_below_the_production_spike_trap() -> None:
    idle = score_risk(_DEV_IDLE)
    spike = score_risk(_SPIKE)
    watched = score_risk(_PROD_INCIDENT)

    assert idle == score_risk(_DEV_IDLE)
    assert idle.risk_score == 0.05
    assert spike.risk_score == 0.65
    assert watched.risk_score == 0.80
    assert idle.risk_score < spike.risk_score < watched.risk_score
    assert idle.reasons
    assert "Environment is development" in idle.reasons
    assert "CPU peak is 100.00" in spike.reasons
    assert "1 incident is recorded, highest severity high" in watched.reasons
    assert "1 resource depends on it" in watched.reasons
    assert idle.risk_class == RiskClass.approval_required
    assert spike.risk_class == RiskClass.approval_required


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


def test_assess_reads_environment_peak_dependencies_and_incidents(session: Session) -> None:
    _plant(session)

    idle = assess(session, "i-risk-idle")
    spike = assess(session, "i-risk-spike")
    watched = assess(session, "i-risk-watched")

    assert idle.risk_score == score_risk(_DEV_IDLE).risk_score
    assert spike.risk_score == score_risk(_SPIKE).risk_score
    assert watched.risk_score == score_risk(_PROD_INCIDENT).risk_score
    assert "Environment is production" in spike.reasons
    assert "1 incident is recorded, highest severity high" in watched.reasons


def _plant(session: Session) -> None:
    resources = ResourceRepository(session)
    resources.upsert(_resource("i-risk-idle", "development", "low"))
    resources.upsert(_resource("db-risk-idle", "development", "low", "database"))
    resources.upsert(_resource("i-risk-spike", "production", "medium"))
    resources.upsert(_resource("db-risk-spike", "production", "low", "database"))
    resources.upsert(_resource("i-risk-watched", "production", "high"))
    resources.upsert(_resource("db-risk-watched", "production", "low", "database"))
    resources.upsert(_resource("lb-risk-watched", "production", "low", "load_balancer"))
    resources.upsert(_resource("bucket-risk-idle", "development", "low", "object_storage"))
    resources.upsert(_resource("bucket-risk-spike", "production", "low", "object_storage"))
    resources.upsert(_resource("bucket-risk-watched", "production", "low", "object_storage"))
    DependencyRepository(session).upsert_many(
        [
            _edge("i-risk-idle", "db-risk-idle", "uses_database"),
            _edge("i-risk-idle", "bucket-risk-idle", "reads_bucket"),
            _edge("i-risk-spike", "db-risk-spike", "uses_database"),
            _edge("i-risk-spike", "bucket-risk-spike", "reads_bucket"),
            _edge("i-risk-watched", "db-risk-watched", "uses_database"),
            _edge("i-risk-watched", "bucket-risk-watched", "reads_bucket"),
            _edge("lb-risk-watched", "i-risk-watched", "routes_to"),
        ]
    )
    IncidentRepository(session).upsert_many(
        [
            Incident(
                incident_id="inc-risk-watched",
                resource_id="i-risk-watched",
                severity="high",
                started_at=datetime(2099, 3, 20, tzinfo=UTC),
                summary="production compute failed a health check",
            )
        ]
    )
    MetricRollupRepository(session).upsert_many(
        [
            _cpu("i-risk-idle", 11.95),
            _cpu("i-risk-spike", 100.0),
            _cpu("i-risk-watched", 11.93),
        ]
    )


def _resource(
    resource_id: str,
    environment: str,
    criticality: str,
    resource_type: str = "compute",
) -> Resource:
    account = "111111111111" if environment == "development" else "333333333333"
    return Resource(
        resource_id=resource_id,
        resource_type=resource_type,
        account_id=account,
        environment=environment,
        owner="payments",
        team="payments",
        business_criticality=criticality,
        tags={"environment": environment, "criticality": criticality},
    )


def _edge(source: str, target: str, relationship: str) -> Dependency:
    return Dependency(
        source_resource_id=source,
        target_resource_id=target,
        relationship=relationship,
    )


def _cpu(resource_id: str, peak: float) -> MetricRollup:
    return MetricRollup(
        resource_id=resource_id,
        name="cpu_percent",
        day=date(2099, 4, 1),
        avg_value=8.0,
        peak_value=peak,
        unit="percent",
    )
