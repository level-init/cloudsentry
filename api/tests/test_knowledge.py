from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import DependencyRepository, IncidentRepository, ResourceRepository
from worker.inventory import resource_from_simulator
from worker.knowledge_ingest import dependencies_from_payload, incidents_from_payload


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


def test_tags_dependencies_and_incidents_round_trip(session: Session) -> None:
    resources = ResourceRepository(session)
    resources.upsert(_resource("i-know-src", scenario="spike_trap"))
    resources.upsert(_resource("i-know-dst"))
    stored = resources.get("i-know-src")
    edges = dependencies_from_payload(
        [
            {
                "source_resource_id": "i-know-src",
                "target_resource_id": "i-know-dst",
                "relationship": "uses_database",
            }
        ]
    )
    incidents = incidents_from_payload(
        [
            {
                "incident_id": "inc-know-1",
                "resource_id": "i-know-src",
                "severity": "high",
                "started_at": "2026-03-20T00:00:00Z",
                "summary": "looked idle",
            }
        ]
    )
    dependencies = DependencyRepository(session)
    incident_repository = IncidentRepository(session)
    created_edges, _updated_edges = dependencies.upsert_many(edges)
    created_incidents, _updated_incidents = incident_repository.upsert_many(incidents)
    changed = incidents[0].model_copy(update={"summary": "still idle"})
    again_edges = dependencies.upsert_many(edges)
    again_incidents = incident_repository.upsert_many([changed])

    assert stored is not None
    assert stored.owner == "payments-oncall"
    assert stored.team == "payments"
    assert stored.business_criticality == "high"
    assert stored.tags["scenario"] == "spike_trap"
    assert created_edges == 1
    assert created_incidents == 1
    assert again_edges == (0, 1)
    assert again_incidents == (0, 1)
    found = dependencies.dependencies_of("i-know-src")
    assert found[0].relationship == "uses_database"
    assert found[0].target_resource_id == "i-know-dst"
    assert dependencies.dependents_of("i-know-dst")[0].source_resource_id == "i-know-src"
    assert incident_repository.for_resource("i-know-src")[0].summary == "still idle"
    assert incident_repository.for_resource("i-know-src")[0].incident_id == "inc-know-1"


def _resource(resource_id: str, scenario: str | None = None) -> object:
    tags = {
        "owner": "payments-oncall",
        "team": "payments",
        "environment": "development",
        "criticality": "high",
    }
    if scenario is not None:
        tags["scenario"] = scenario
    return resource_from_simulator(
        {
            "resource_id": resource_id,
            "resource_type": "compute",
            "account_id": "111111111111",
            "environment": "development",
            "tags": tags,
        }
    )
