"""Ownership and criticality tags for seeded resources.

Tags are stored on each resource so a later read API can filter them.
This is not a CMDB.
"""

import hashlib

from simulator.model import Environment, Inventory, ResourceType, SimResource

_TEAMS = (
    ("payments", "payments-oncall"),
    ("platform", "platform-oncall"),
    ("data", "data-oncall"),
)

_CRITICAL_TYPES = {
    ResourceType.database,
    ResourceType.load_balancer,
    ResourceType.cluster,
}


def resource_tags(
    resource_id: str,
    resource_type: ResourceType,
    environment: Environment,
) -> dict[str, str]:
    team, owner = _TEAMS[_digest(resource_id) % len(_TEAMS)]
    return {
        "owner": owner,
        "team": team,
        "environment": environment.value,
        "criticality": _criticality(resource_id, resource_type, environment),
    }


def resources_by_tag(inventory: Inventory, key: str, value: str) -> list[SimResource]:
    return [resource for resource in inventory.resources if resource.tags.get(key) == value]


def main() -> None:
    from simulator.seed import seed_company

    inventory = seed_company()
    print(f"tagged resources: {len(inventory.resources)}")
    for resource in inventory.resources[:10]:
        print(f"{resource.resource_id} {resource.tags}")
    critical = resources_by_tag(inventory, "criticality", "high")
    prod_critical = [
        resource for resource in critical if resource.environment == Environment.production
    ]
    print(f"production critical: {len(prod_critical)}")


def _criticality(resource_id: str, resource_type: ResourceType, environment: Environment) -> str:
    if environment == Environment.development:
        return "low"
    if environment == Environment.staging:
        return "medium"
    if resource_type in _CRITICAL_TYPES or _digest(resource_id) % 4 == 0:
        return "high"
    return "medium"


def _digest(resource_id: str) -> int:
    return hashlib.sha256(resource_id.encode()).digest()[0]


if __name__ == "__main__":
    main()
