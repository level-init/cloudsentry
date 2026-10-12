"""Directed dependencies for the seeded company.

An edge means the source resource depends on the target. Lists of dependencies
and dependents are ready for a later read API. This is not a graph database.
"""

from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from simulator.model import Environment, Inventory, ResourceType, SimResource
from simulator.seed import seed_company


class DependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_resource_id: str = Field(min_length=1)
    target_resource_id: str = Field(min_length=1)
    relationship: str = Field(min_length=1)

    @model_validator(mode="after")
    def endpoints_differ(self) -> "DependencyEdge":
        if self.source_resource_id == self.target_resource_id:
            raise ValueError("source_resource_id and target_resource_id must differ")
        return self


_WALK_ORDER = ("uses_database", "stores_on", "routes_to", "snapshot_of", "reads_bucket")


class DependencyGraph:
    def __init__(self, inventory: Inventory, edges: list[DependencyEdge]) -> None:
        self._ids = {resource.resource_id for resource in inventory.resources}
        for edge in edges:
            if edge.source_resource_id not in self._ids or edge.target_resource_id not in self._ids:
                raise ValueError("dependency endpoint is not in the inventory")
        self.edges = list(edges)

    def dependencies(self, resource_id: str) -> list[DependencyEdge]:
        self._require(resource_id)
        return [edge for edge in self.edges if edge.source_resource_id == resource_id]

    def dependents(self, resource_id: str) -> list[DependencyEdge]:
        self._require(resource_id)
        return [edge for edge in self.edges if edge.target_resource_id == resource_id]

    def path(self, resource_id: str) -> list[str]:
        self._require(resource_id)
        walked = [resource_id]
        seen = {resource_id}
        current = resource_id
        while True:
            outgoing = self.dependencies(current)
            if not outgoing:
                return walked
            chosen = min(outgoing, key=lambda edge: _WALK_ORDER.index(edge.relationship))
            target = chosen.target_resource_id
            if target in seen:
                return walked
            walked.append(target)
            seen.add(target)
            current = target

    def _require(self, resource_id: str) -> None:
        if resource_id not in self._ids:
            raise ValueError(f"unknown resource {resource_id}")


def dependency_graph(inventory: Inventory) -> DependencyGraph:
    edges: list[DependencyEdge] = []
    for account in inventory.accounts:
        edges.extend(_account_edges(inventory.resources_for(account.account_id)))
    return DependencyGraph(inventory, edges)


def demo_chain(inventory: Inventory) -> list[str]:
    graph = dependency_graph(inventory)
    app = _first_of(inventory, Environment.production, ResourceType.compute)
    return graph.path(app.resource_id)


def main() -> None:
    inventory = seed_company()
    graph = dependency_graph(inventory)
    chain = demo_chain(inventory)
    print("demo chain: " + " -> ".join(chain))
    for resource_id in chain:
        outgoing = graph.dependencies(resource_id)
        if not outgoing:
            print(f"{resource_id}: no further dependencies")
            continue
        edge = outgoing[0]
        print(f"{edge.source_resource_id} {edge.relationship} {edge.target_resource_id}")


def _account_edges(resources: list[SimResource]) -> list[DependencyEdge]:
    grouped: dict[ResourceType, list[SimResource]] = defaultdict(list)
    for resource in sorted(resources, key=lambda item: item.resource_id):
        grouped[resource.resource_type].append(resource)
    edges: list[DependencyEdge] = []
    _link(edges, grouped[ResourceType.database], grouped[ResourceType.disk], "stores_on")
    _link(edges, grouped[ResourceType.compute], grouped[ResourceType.database], "uses_database")
    _link(edges, grouped[ResourceType.load_balancer], grouped[ResourceType.compute], "routes_to")
    _link(edges, grouped[ResourceType.snapshot], grouped[ResourceType.disk], "snapshot_of")
    _link(
        edges,
        grouped[ResourceType.compute],
        grouped[ResourceType.object_storage],
        "reads_bucket",
    )
    return edges


def _link(
    edges: list[DependencyEdge],
    sources: list[SimResource],
    targets: list[SimResource],
    relationship: str,
) -> None:
    if not sources or not targets:
        return
    for index, source in enumerate(sources):
        target = targets[index % len(targets)]
        edges.append(
            DependencyEdge(
                source_resource_id=source.resource_id,
                target_resource_id=target.resource_id,
                relationship=relationship,
            )
        )


def _first_of(
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
