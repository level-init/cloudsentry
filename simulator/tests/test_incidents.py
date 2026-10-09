from datetime import timedelta

import pytest

from simulator.incidents import incidents_for, seed_incidents
from simulator.metrics import HISTORY_END, UsageProfile, usage_profile
from simulator.model import Environment, ResourceType
from simulator.seed import seed_company


def test_idle_production_compute_has_a_recent_incident() -> None:
    inventory = seed_company()
    incidents = seed_incidents(inventory)
    idle = next(resource for resource in inventory.resources if resource.resource_id == "i-prd-005")
    assert usage_profile(idle.resource_id) == UsageProfile.steady_low
    assert idle.environment == Environment.production
    listed = incidents_for(inventory, incidents, idle.resource_id)

    assert listed
    incident = listed[0]
    assert incident.severity == "high"
    assert HISTORY_END - timedelta(days=30) <= incident.started_at < HISTORY_END
    assert incident.summary


def test_incidents_are_listed_only_for_their_resource() -> None:
    inventory = seed_company()
    incidents = seed_incidents(inventory)
    database = next(
        resource
        for resource in inventory.resources
        if resource.environment == Environment.production
        and resource.resource_type == ResourceType.database
    )
    listed = incidents_for(inventory, incidents, database.resource_id)

    assert [incident.incident_id for incident in listed] == ["inc-prd-db"]
    assert all(incident.resource_id == database.resource_id for incident in listed)


def test_seed_is_repeatable() -> None:
    inventory = seed_company()

    first = [incident.model_dump() for incident in seed_incidents(inventory)]
    second = [incident.model_dump() for incident in seed_incidents(inventory)]
    assert first == second


def test_unknown_resource_is_rejected() -> None:
    inventory = seed_company()

    with pytest.raises(ValueError):
        incidents_for(inventory, seed_incidents(inventory), "i-missing")
