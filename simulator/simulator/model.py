"""In-memory accounts, environments, and resources for the AWS-like simulator.

IDs are stable: the same resource type and suffix always produce the same id.
This module does not call AWS. The AWS-like names are documented in
simulator/README.md.
"""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SUFFIX = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Environment(StrEnum):
    development = "development"
    staging = "staging"
    production = "production"


class ResourceType(StrEnum):
    compute = "compute"
    disk = "disk"
    object_storage = "object_storage"
    database = "database"
    load_balancer = "load_balancer"
    snapshot = "snapshot"
    cluster = "cluster"


# Prefixes are AWS-like and disjoint once the hyphen is required.
_PREFIX: dict[ResourceType, str] = {
    ResourceType.compute: "i",
    ResourceType.disk: "vol",
    ResourceType.object_storage: "bucket",
    ResourceType.database: "db",
    ResourceType.load_balancer: "lb",
    ResourceType.snapshot: "snap",
    ResourceType.cluster: "cluster",
}

# Resource types the five MVP detectors need. Other types exist for inventory.
MVP_DETECTOR_TYPES: dict[str, frozenset[ResourceType]] = {
    "idle_compute": frozenset({ResourceType.compute}),
    "compute_rightsizing": frozenset({ResourceType.compute}),
    "development_scheduling": frozenset({ResourceType.compute}),
    "unattached_storage": frozenset({ResourceType.disk, ResourceType.snapshot}),
    "storage_lifecycle": frozenset({ResourceType.object_storage}),
}


def resource_id(resource_type: ResourceType, suffix: str) -> str:
    if _SUFFIX.fullmatch(suffix) is None:
        raise ValueError("suffix must be lowercase letters, digits, and hyphens")
    return f"{_PREFIX[resource_type]}-{suffix}"


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(pattern=r"^\d{12}$")
    name: str = Field(min_length=1)
    environment: Environment


class SimResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    resource_type: ResourceType
    account_id: str = Field(pattern=r"^\d{12}$")
    environment: Environment
    name: str = Field(min_length=1)
    tags: dict[str, str] = Field(default_factory=dict)
    sku: str | None = None
    power_state: str | None = None
    schedule: str | None = None
    storage_class: str | None = None


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accounts: list[Account]
    resources: list[SimResource]

    @model_validator(mode="after")
    def consistent(self) -> "Inventory":
        accounts = {account.account_id: account for account in self.accounts}
        if len(accounts) != len(self.accounts):
            raise ValueError("account_id values must be unique")
        seen: set[str] = set()
        for resource in self.resources:
            if resource.resource_id in seen:
                raise ValueError(f"duplicate resource_id {resource.resource_id}")
            seen.add(resource.resource_id)
            account = accounts.get(resource.account_id)
            if account is None:
                raise ValueError(f"unknown account {resource.account_id}")
            if resource.environment != account.environment:
                raise ValueError(f"{resource.resource_id} environment does not match its account")
            prefix = f"{_PREFIX[resource.resource_type]}-"
            if not resource.resource_id.startswith(prefix):
                raise ValueError(f"{resource.resource_id} does not match {resource.resource_type}")
        return self

    def resources_for(self, account_id: str) -> list[SimResource]:
        return [resource for resource in self.resources if resource.account_id == account_id]
