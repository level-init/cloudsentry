from simulator.model import Environment, ResourceType
from simulator.seed import seed_company
from simulator.tags import resources_by_tag

_REQUIRED = ("owner", "team", "environment", "criticality")


def test_every_seeded_resource_has_owner_and_environment() -> None:
    inventory = seed_company()

    assert len(inventory.resources) >= 10
    for resource in inventory.resources:
        for key in _REQUIRED:
            assert resource.tags[key]
        assert resource.tags["environment"] == resource.environment
        assert resource.tags["criticality"] in {"low", "medium", "high"}


def test_production_critical_resources_are_marked() -> None:
    inventory = seed_company()
    critical = resources_by_tag(inventory, "criticality", "high")
    prod_databases = [
        resource
        for resource in inventory.resources
        if resource.environment == Environment.production
        and resource.resource_type == ResourceType.database
    ]

    assert critical
    assert all(resource.environment == Environment.production for resource in critical)
    assert prod_databases
    assert all(resource.tags["criticality"] == "high" for resource in prod_databases)


def test_development_resources_are_low_criticality() -> None:
    inventory = seed_company()
    development = resources_by_tag(inventory, "environment", "development")

    assert development
    assert all(resource.tags["criticality"] == "low" for resource in development)
