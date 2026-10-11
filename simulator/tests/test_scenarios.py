from pathlib import Path

from simulator.billing import sku_for
from simulator.dependencies import dependency_graph
from simulator.metrics import UsageProfile, cpu_avg_and_peak, usage_profile
from simulator.scenarios import EXPECTED, SCENARIOS
from simulator.seed import seed_company

_DOC = Path(__file__).resolve().parents[1] / "DEMO_SCENARIOS.md"


def test_documented_ids_exist_in_the_seed() -> None:
    inventory = seed_company()
    by_id = {resource.resource_id: resource for resource in inventory.resources}
    document = _DOC.read_text()

    assert len(SCENARIOS) == 7
    for scenario in SCENARIOS:
        resource = by_id[scenario.resource_id]
        environment, resource_type, profile, sku = EXPECTED[scenario.resource_id]
        assert scenario.resource_id in document
        assert resource.name == scenario.name
        assert resource.tags["scenario"] == scenario.key
        assert resource.environment == environment
        assert resource.resource_type == resource_type
        assert usage_profile(resource.resource_id) == UsageProfile(profile)
        assert sku_for(resource)[0] == sku


def test_each_mvp_detector_has_a_fixture() -> None:
    detectors = {scenario.detector for scenario in SCENARIOS}

    assert {
        "idle_compute",
        "development_scheduling",
        "compute_rightsizing",
        "unattached_storage",
        "storage_lifecycle",
        "veto_rightsizing",
    } <= detectors


def test_unattached_disk_has_no_dependents() -> None:
    inventory = seed_company()
    graph = dependency_graph(inventory)

    assert graph.dependents("vol-dev-042") == []


def test_spike_trap_peak_must_not_be_rightsized_from_the_average() -> None:
    inventory = seed_company()
    average, peak = cpu_avg_and_peak(inventory, "i-prd-017")

    assert average < 20
    assert peak > average * 3
