"""Copy simulator dependencies, incidents, and resource tags into Postgres.

Tags and ownership are written onto the resource row. Each dependency edge is
stored once. Incidents are stored by incident id. A second run updates those
same rows.
"""

import logging
from dataclasses import dataclass

from app.db import create_session
from app.repositories import DependencyRepository, IncidentRepository
from app.schemas import Dependency, Incident
from worker.config import get_settings
from worker.inventory import fetch_resources, get_json, ingest_resources, resource_from_simulator


@dataclass(frozen=True)
class KnowledgeIngestCounts:
    resources_created: int
    resources_updated: int
    resources_absent: int
    dependencies_created: int
    dependencies_updated: int
    incidents_created: int
    incidents_updated: int


def ingest_knowledge(base_url: str | None = None) -> KnowledgeIngestCounts:
    url = (base_url or get_settings().simulator_base_url).rstrip("/")
    payloads = fetch_resources(url)
    session = create_session()
    try:
        resource_counts = ingest_resources(
            session,
            [resource_from_simulator(payload) for payload in payloads],
        )
        edges: list[Dependency] = []
        incidents: list[Incident] = []
        for payload in payloads:
            resource_id = payload["resource_id"]
            dependency_items = get_json(f"{url}/resources/{resource_id}/dependencies")
            incident_items = get_json(f"{url}/resources/{resource_id}/incidents")
            edges.extend(dependencies_from_payload(dependency_items))
            incidents.extend(incidents_from_payload(incident_items))
            logging.info(
                "knowledge %s dependencies=%s incidents=%s",
                resource_id,
                len(dependency_items),
                len(incident_items),
            )
        dependencies_created, dependencies_updated = DependencyRepository(session).upsert_many(
            edges
        )
        incidents_created, incidents_updated = IncidentRepository(session).upsert_many(incidents)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return KnowledgeIngestCounts(
        resource_counts.created,
        resource_counts.updated,
        resource_counts.absent,
        dependencies_created,
        dependencies_updated,
        incidents_created,
        incidents_updated,
    )


def dependencies_from_payload(items: list[dict]) -> list[Dependency]:
    return [Dependency.model_validate(item) for item in items]


def incidents_from_payload(items: list[dict]) -> list[Incident]:
    return [Incident.model_validate(item) for item in items]
