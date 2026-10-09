import pytest

from simulator.dependencies import demo_chain, dependency_graph
from simulator.model import ResourceType
from simulator.seed import seed_company


def test_demo_chain_walks_app_to_database_to_disk() -> None:
    inventory = seed_company()
    graph = dependency_graph(inventory)
    chain = demo_chain(inventory)
    by_id = {resource.resource_id: resource for resource in inventory.resources}

    assert chain == ["i-prd-000", "db-prd-014", "vol-prd-003"]
    assert [by_id[resource_id].resource_type for resource_id in chain] == [
        ResourceType.compute,
        ResourceType.database,
        ResourceType.disk,
    ]
    assert graph.path(chain[0]) == chain
    app_edge = graph.dependencies(chain[0])[0]
    db_edge = graph.dependencies(chain[1])[0]
    assert app_edge.relationship == "uses_database"
    assert app_edge.target_resource_id == chain[1]
    assert db_edge.relationship == "stores_on"
    assert db_edge.target_resource_id == chain[2]
    assert graph.dependents(chain[1])
    assert graph.dependents(chain[2])


def test_edges_stay_inside_known_resources() -> None:
    inventory = seed_company()
    graph = dependency_graph(inventory)
    ids = {resource.resource_id for resource in inventory.resources}

    assert graph.edges
    for edge in graph.edges:
        assert edge.source_resource_id in ids
        assert edge.target_resource_id in ids
        assert edge.source_resource_id != edge.target_resource_id


def test_graph_is_repeatable() -> None:
    inventory = seed_company()
    first = dependency_graph(inventory)
    second = dependency_graph(seed_company())

    first_dump = [edge.model_dump() for edge in first.edges]
    second_dump = [edge.model_dump() for edge in second.edges]
    assert first_dump == second_dump


def test_unknown_resource_is_rejected() -> None:
    graph = dependency_graph(seed_company())

    with pytest.raises(ValueError):
        graph.dependencies("i-missing")
