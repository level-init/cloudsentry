import pytest
from pydantic import ValidationError

from simulator.model import (
    MVP_DETECTOR_TYPES,
    Account,
    Environment,
    Inventory,
    ResourceType,
    SimResource,
    resource_id,
)


def test_resource_id_is_stable() -> None:
    first = resource_id(ResourceType.compute, "idle-dev")
    second = resource_id(ResourceType.compute, "idle-dev")

    assert first == second == "i-idle-dev"
    assert resource_id(ResourceType.disk, "orphan") == "vol-orphan"


def test_resource_id_rejects_unstable_suffix() -> None:
    with pytest.raises(ValueError):
        resource_id(ResourceType.compute, "Idle_Dev")


def test_mini_inventory_spans_accounts_and_types() -> None:
    dev = Account(account_id="111111111111", name="payments-dev", environment="development")
    prod = Account(account_id="222222222222", name="payments-prod", environment="production")
    resources = [
        _resource(ResourceType.compute, "idle-dev", dev, "idle dev instance"),
        _resource(ResourceType.disk, "orphan", dev, "unattached volume"),
        _resource(ResourceType.snapshot, "old", dev, "old snapshot"),
        _resource(ResourceType.object_storage, "logs", dev, "log bucket"),
        _resource(ResourceType.database, "app", prod, "app database"),
        _resource(ResourceType.load_balancer, "edge", prod, "edge balancer"),
        _resource(ResourceType.cluster, "workers", prod, "worker cluster"),
    ]

    inventory = Inventory(accounts=[dev, prod], resources=resources)

    assert {account.environment for account in inventory.accounts} == {
        Environment.development,
        Environment.production,
    }
    assert {resource.resource_type for resource in inventory.resources} == set(ResourceType)
    assert len(inventory.resources_for(dev.account_id)) == 4
    assert len(inventory.resources_for(prod.account_id)) == 3


def test_resource_types_cover_mvp_detectors() -> None:
    covered = set().union(*MVP_DETECTOR_TYPES.values())

    assert set(MVP_DETECTOR_TYPES) == {
        "idle_compute",
        "compute_rightsizing",
        "development_scheduling",
        "unattached_storage",
        "storage_lifecycle",
    }
    assert covered <= set(ResourceType)


def test_inventory_rejects_unknown_account_and_env_mismatch() -> None:
    dev = Account(account_id="111111111111", name="payments-dev", environment="development")
    with pytest.raises(ValidationError):
        Inventory(
            accounts=[dev],
            resources=[
                _resource(ResourceType.compute, "idle-dev", dev, "idle").model_copy(
                    update={"account_id": "999999999999"}
                )
            ],
        )
    with pytest.raises(ValidationError):
        Inventory(
            accounts=[dev],
            resources=[
                _resource(ResourceType.compute, "idle-dev", dev, "idle").model_copy(
                    update={"environment": Environment.production}
                )
            ],
        )


def test_inventory_rejects_id_that_does_not_match_type() -> None:
    dev = Account(account_id="111111111111", name="payments-dev", environment="development")
    with pytest.raises(ValidationError):
        Inventory(
            accounts=[dev],
            resources=[
                _resource(ResourceType.compute, "idle-dev", dev, "idle").model_copy(
                    update={"resource_id": "vol-idle-dev"}
                )
            ],
        )


def _resource(
    resource_type: ResourceType,
    suffix: str,
    account: Account,
    name: str,
) -> SimResource:
    return SimResource(
        resource_id=resource_id(resource_type, suffix),
        resource_type=resource_type,
        account_id=account.account_id,
        environment=account.environment,
        name=name,
    )
