"""Mutable simulator world.

The seed is copied once. Actions change that copy and remember the prior
field so rollback can restore it. This does not call AWS.
"""

from simulator.billing import sku_for
from simulator.dependencies import DependencyGraph, dependency_graph
from simulator.incidents import Incident, seed_incidents
from simulator.model import Inventory, ResourceType, SimResource
from simulator.seed import seed_company

COMPUTE_SKUS = ("t3.medium", "m5.large", "m5.xlarge")
SCHEDULES = ("always_on", "weekdays-09-17")
STORAGE_CLASSES = ("standard", "infrequent_access")


class Mutation:
    def __init__(
        self,
        action_id: str,
        action: str,
        resource_id: str,
        field: str,
        prior: str | None,
        prior_resource: SimResource | None,
        index: int | None,
    ) -> None:
        self.action_id = action_id
        self.action = action
        self.resource_id = resource_id
        self.field = field
        self.prior = prior
        self.prior_resource = prior_resource
        self.index = index
        self.rolled_back = False


class World:
    def __init__(self) -> None:
        seeded = seed_company()
        resources = [_with_defaults(resource) for resource in seeded.resources]
        self.inventory = Inventory(accounts=list(seeded.accounts), resources=resources)
        self.graph: DependencyGraph = dependency_graph(self.inventory)
        self.incidents: list[Incident] = seed_incidents(self.inventory)
        self._mutations: dict[str, Mutation] = {}
        self._next_action = 1

    def stop(self, resource_id: str) -> Mutation:
        resource = self._require(resource_id)
        _require_compute(resource, "stop")
        if resource.power_state == "stopped":
            raise ValueError("compute is already stopped")
        return self._update(resource, "stop", "power_state", "stopped")

    def start(self, resource_id: str) -> Mutation:
        resource = self._require(resource_id)
        _require_compute(resource, "start")
        if resource.power_state == "running":
            raise ValueError("compute is already running")
        return self._update(resource, "start", "power_state", "running")

    def resize(self, resource_id: str, sku: str) -> Mutation:
        resource = self._require(resource_id)
        _require_compute(resource, "resize")
        if sku not in COMPUTE_SKUS:
            raise ValueError(f"unknown compute sku {sku}")
        if resource.sku == sku:
            raise ValueError(f"compute is already {sku}")
        return self._update(resource, "resize", "sku", sku)

    def schedule(self, resource_id: str, schedule: str) -> Mutation:
        resource = self._require(resource_id)
        _require_compute(resource, "schedule")
        if resource.environment != "development":
            raise ValueError("schedule applies only to development compute")
        if schedule not in SCHEDULES:
            raise ValueError(f"unknown schedule {schedule}")
        if resource.schedule == schedule:
            raise ValueError(f"schedule is already {schedule}")
        return self._update(resource, "schedule", "schedule", schedule)

    def delete_unattached(self, resource_id: str) -> Mutation:
        resource = self._require(resource_id)
        if resource.resource_type != ResourceType.disk:
            raise ValueError("delete_unattached applies only to disks")
        if self.graph.dependents(resource_id):
            raise ValueError("disk has dependents")
        index = self._index(resource_id)
        mutation = self._record("delete_unattached", resource_id, "present", None, resource, index)
        self.inventory.resources.pop(index)
        self.graph = dependency_graph(self.inventory)
        return mutation

    def storage_lifecycle(self, resource_id: str, storage_class: str) -> Mutation:
        resource = self._require(resource_id)
        if resource.resource_type != ResourceType.object_storage:
            raise ValueError("storage_lifecycle applies only to object storage")
        if storage_class not in STORAGE_CLASSES:
            raise ValueError(f"unknown storage class {storage_class}")
        if resource.storage_class == storage_class:
            raise ValueError(f"storage class is already {storage_class}")
        return self._update(resource, "storage_lifecycle", "storage_class", storage_class)

    def rollback(self, action_id: str) -> SimResource:
        mutation = self._mutations.get(action_id)
        if mutation is None:
            raise ValueError(f"unknown action {action_id}")
        if mutation.rolled_back:
            raise ValueError("action is already rolled back")
        mutation.rolled_back = True
        if mutation.prior_resource is not None:
            index = mutation.index if mutation.index is not None else len(self.inventory.resources)
            self.inventory.resources.insert(index, mutation.prior_resource)
            self.graph = dependency_graph(self.inventory)
            return mutation.prior_resource
        current = self._require(mutation.resource_id)
        restored = current.model_copy(update={mutation.field: mutation.prior})
        self.inventory.resources[self._index(mutation.resource_id)] = restored
        return restored

    def _update(self, resource: SimResource, action: str, field: str, value: str) -> Mutation:
        mutation = self._record(
            action,
            resource.resource_id,
            field,
            getattr(resource, field),
            None,
            None,
        )
        updated = resource.model_copy(update={field: value})
        self.inventory.resources[self._index(resource.resource_id)] = updated
        return mutation

    def _record(
        self,
        action: str,
        resource_id: str,
        field: str,
        prior: str | None,
        prior_resource: SimResource | None,
        index: int | None,
    ) -> Mutation:
        action_id = f"act-{self._next_action}"
        self._next_action += 1
        mutation = Mutation(action_id, action, resource_id, field, prior, prior_resource, index)
        self._mutations[action_id] = mutation
        return mutation

    def _require(self, resource_id: str) -> SimResource:
        resource = next(
            (item for item in self.inventory.resources if item.resource_id == resource_id),
            None,
        )
        if resource is None:
            raise ValueError(f"unknown resource {resource_id}")
        return resource

    def _index(self, resource_id: str) -> int:
        for index, resource in enumerate(self.inventory.resources):
            if resource.resource_id == resource_id:
                return index
        raise ValueError(f"unknown resource {resource_id}")


def _with_defaults(resource: SimResource) -> SimResource:
    sku, _cents = sku_for(resource)
    updates: dict[str, str] = {"sku": sku}
    if resource.resource_type == ResourceType.compute:
        updates["power_state"] = "running"
        updates["schedule"] = "always_on"
    if resource.resource_type == ResourceType.object_storage:
        updates["storage_class"] = "standard"
    return resource.model_copy(update=updates)


def _require_compute(resource: SimResource, action: str) -> None:
    if resource.resource_type != ResourceType.compute:
        raise ValueError(f"{action} applies only to compute")
