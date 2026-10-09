"""Historical incidents for the seeded company.

Incidents are linked to resource ids and can be listed per resource. This is
not an ITSM integration.
"""

from datetime import datetime, timedelta, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from simulator.metrics import HISTORY_END, UsageProfile, usage_profile
from simulator.model import Environment, Inventory, ResourceType, SimResource
from simulator.seed import seed_company


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    severity: Severity
    started_at: datetime
    summary: str = Field(min_length=1)


def seed_incidents(inventory: Inventory) -> list[Incident]:
    idle = idle_production_compute(inventory)
    database = _first(inventory, Environment.production, ResourceType.database)
    staging = _first(inventory, Environment.staging, ResourceType.compute)
    incidents = [
        Incident(
            incident_id="inc-prd-idle",
            resource_id=idle.resource_id,
            severity=Severity.high,
            started_at=HISTORY_END - timedelta(days=12),
            summary="production compute looked idle but failed a health check",
        ),
        Incident(
            incident_id="inc-prd-db",
            resource_id=database.resource_id,
            severity=Severity.medium,
            started_at=datetime(2026, 2, 3, 16, tzinfo=timezone.utc),
            summary="production database connection spike",
        ),
        Incident(
            incident_id="inc-stg-compute",
            resource_id=staging.resource_id,
            severity=Severity.low,
            started_at=datetime(2026, 1, 15, 11, tzinfo=timezone.utc),
            summary="staging compute restart during a deploy",
        ),
    ]
    return sorted(incidents, key=lambda incident: incident.started_at)


def incidents_for(
    inventory: Inventory,
    incidents: list[Incident],
    resource_id: str,
) -> list[Incident]:
    known = {resource.resource_id for resource in inventory.resources}
    if resource_id not in known:
        raise ValueError(f"unknown resource {resource_id}")
    return [incident for incident in incidents if incident.resource_id == resource_id]


def idle_production_compute(inventory: Inventory) -> SimResource:
    matches = [
        resource
        for resource in inventory.resources
        if resource.environment == Environment.production
        and resource.resource_type == ResourceType.compute
        and usage_profile(resource.resource_id) == UsageProfile.steady_low
    ]
    if not matches:
        raise ValueError("no idle production compute in the seed")
    return min(matches, key=lambda resource: resource.resource_id)


def main() -> None:
    inventory = seed_company()
    incidents = seed_incidents(inventory)
    idle = idle_production_compute(inventory)
    listed = incidents_for(inventory, incidents, idle.resource_id)
    print(f"idle production compute: {idle.resource_id}")
    for incident in listed:
        started = incident.started_at.date().isoformat()
        print(f"{incident.incident_id} {incident.severity} {started} {incident.summary}")


def _first(
    inventory: Inventory,
    environment: Environment,
    resource_type: ResourceType,
) -> SimResource:
    matches = [
        resource
        for resource in inventory.resources
        if resource.environment == environment and resource.resource_type == resource_type
    ]
    return min(matches, key=lambda resource: resource.resource_id)


if __name__ == "__main__":
    main()
