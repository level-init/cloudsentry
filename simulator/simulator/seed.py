"""Deterministic company inventory.

`reset_seed` rebuilds the in-memory world from a fixed RNG seed. The same
seed always yields the same accounts, resource ids, and counts.
"""

import random

from simulator.model import Account, Environment, Inventory, ResourceType, SimResource, resource_id
from simulator.tags import resource_tags

SEED = 30

_ENV_CODE = {
    Environment.development: "dev",
    Environment.staging: "stg",
    Environment.production: "prd",
}

_COUNTS = {
    Environment.development: 70,
    Environment.staging: 50,
    Environment.production: 60,
}

_WEIGHTED: tuple[ResourceType, ...] = (
    (ResourceType.compute,) * 8
    + (ResourceType.disk,) * 4
    + (ResourceType.snapshot,) * 2
    + (ResourceType.object_storage,) * 2
    + (ResourceType.database,)
    + (ResourceType.load_balancer,)
    + (ResourceType.cluster,)
)

ACCOUNTS = (
    Account(account_id="111111111111", name="payments-dev", environment=Environment.development),
    Account(
        account_id="222222222222",
        name="payments-staging",
        environment=Environment.staging,
    ),
    Account(account_id="333333333333", name="payments-prod", environment=Environment.production),
)

_inventory: Inventory | None = None


def seed_company(seed: int = SEED) -> Inventory:
    rng = random.Random(seed)
    resources: list[SimResource] = []
    for account in ACCOUNTS:
        code = _ENV_CODE[account.environment]
        types = _resource_types(rng, _COUNTS[account.environment])
        for index, resource_type in enumerate(types):
            suffix = f"{code}-{index:03d}"
            assigned_id = resource_id(resource_type, suffix)
            resources.append(
                SimResource(
                    resource_id=assigned_id,
                    resource_type=resource_type,
                    account_id=account.account_id,
                    environment=account.environment,
                    name=f"{resource_type.value}-{suffix}",
                    tags=resource_tags(assigned_id, resource_type, account.environment),
                )
            )
    return Inventory(accounts=list(ACCOUNTS), resources=resources)


def reset_seed() -> Inventory:
    global _inventory
    _inventory = seed_company()
    return _inventory


def _resource_types(rng: random.Random, count: int) -> list[ResourceType]:
    baseline = list(ResourceType)
    extra = [rng.choice(_WEIGHTED) for _ in range(count - len(baseline))]
    types = baseline + extra
    rng.shuffle(types)
    return types


def main() -> None:
    inventory = reset_seed()
    print(f"seed: {SEED}")
    print(f"accounts: {len(inventory.accounts)}")
    print(f"resources: {len(inventory.resources)}")
    for account in inventory.accounts:
        owned = inventory.resources_for(account.account_id)
        print(f"  {account.name} ({account.environment}): {len(owned)}")
        counts: dict[str, int] = {}
        for resource in owned:
            counts[resource.resource_type] = counts.get(resource.resource_type, 0) + 1
        for resource_type in ResourceType:
            print(f"    {resource_type}: {counts.get(resource_type, 0)}")


if __name__ == "__main__":
    main()
