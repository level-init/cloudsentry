"""Named waste fixtures in the seeded company.

These ids already exist in the seed. Renaming them and tagging `scenario`
makes the demo fixtures explicit. Extra undocumented waste is out of scope.
"""

from simulator.model import Environment, ResourceType


class WasteScenario:
    def __init__(
        self,
        key: str,
        resource_id: str,
        name: str,
        detector: str,
        note: str,
    ) -> None:
        self.key = key
        self.resource_id = resource_id
        self.name = name
        self.detector = detector
        self.note = note


SCENARIOS: tuple[WasteScenario, ...] = (
    WasteScenario(
        "idle_compute",
        "i-dev-062",
        "idle-dev-vm",
        "idle_compute",
        "Development compute with a flat low CPU. Positive fixture for idle compute.",
    ),
    WasteScenario(
        "always_on_dev",
        "i-dev-026",
        "always-on-dev",
        "development_scheduling",
        "Development compute that stays busy overnight and on weekends.",
    ),
    WasteScenario(
        "oversized_compute",
        "i-prd-013",
        "oversized-prod",
        "compute_rightsizing",
        "Production m5.xlarge with a flat low CPU. Positive fixture for rightsizing.",
    ),
    WasteScenario(
        "unattached_disk",
        "vol-dev-042",
        "unattached-disk",
        "unattached_storage",
        "Development gp3 500 GB volume with nothing depending on it.",
    ),
    WasteScenario(
        "expensive_storage",
        "bucket-prd-022",
        "expensive-bucket",
        "storage_lifecycle",
        "Production 5 TB standard bucket. Positive fixture for storage lifecycle.",
    ),
    WasteScenario(
        "expensive_snapshot",
        "snap-dev-007",
        "expensive-snapshot",
        "storage_lifecycle",
        "Development 1 TB snapshot. Second storage-lifecycle fixture.",
    ),
    WasteScenario(
        "spike_trap",
        "i-prd-017",
        "spike-trap-prod",
        "veto_rightsizing",
        "Production m5.xlarge with a low average and a Wednesday peak. Do not rightsize.",
    ),
)

_BY_ID = {scenario.resource_id: scenario for scenario in SCENARIOS}

# Expected shape of each planted resource. Tests cross-check the seed against this.
EXPECTED: dict[str, tuple[Environment, ResourceType, str, str]] = {
    "i-dev-062": (Environment.development, ResourceType.compute, "steady_low", "t3.medium"),
    "i-dev-026": (Environment.development, ResourceType.compute, "steady_mid", "m5.large"),
    "i-prd-013": (Environment.production, ResourceType.compute, "steady_low", "m5.xlarge"),
    "vol-dev-042": (Environment.development, ResourceType.disk, "steady_mid", "gp3-500gb"),
    "bucket-prd-022": (
        Environment.production,
        ResourceType.object_storage,
        "steady_mid",
        "s3-standard-5tb",
    ),
    "snap-dev-007": (Environment.development, ResourceType.snapshot, "steady_mid", "snapshot-1tb"),
    "i-prd-017": (Environment.production, ResourceType.compute, "spike_trap", "m5.xlarge"),
}


def scenario_for(resource_id: str) -> WasteScenario | None:
    return _BY_ID.get(resource_id)


def main() -> None:
    from simulator.seed import seed_company

    inventory = seed_company()
    by_id = {resource.resource_id: resource for resource in inventory.resources}
    for scenario in SCENARIOS:
        resource = by_id[scenario.resource_id]
        print(f"{scenario.key}: {resource.resource_id} {resource.name} {resource.tags['scenario']}")


if __name__ == "__main__":
    main()
