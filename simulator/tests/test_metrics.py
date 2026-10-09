from datetime import timedelta

import pytest

from simulator.metrics import (
    HISTORY_DAYS,
    HISTORY_END,
    UsageProfile,
    cpu_avg_and_peak,
    history_start,
    query_metrics,
    usage_profile,
)
from simulator.model import ResourceType
from simulator.seed import seed_company


def test_compute_history_covers_at_least_90_days() -> None:
    inventory = seed_company()
    compute = _first(inventory, ResourceType.compute)
    samples = query_metrics(
        inventory,
        compute.resource_id,
        start=history_start(),
        end=HISTORY_END,
        name="cpu_percent",
    )

    assert HISTORY_DAYS >= 90
    assert len(samples) == HISTORY_DAYS * 24
    assert samples[0].timestamp == history_start()
    assert samples[-1].timestamp == HISTORY_END - timedelta(hours=1)


def test_query_is_limited_to_the_requested_range() -> None:
    inventory = seed_company()
    compute = _first(inventory, ResourceType.compute)
    start = history_start() + timedelta(days=10, hours=4)
    samples = query_metrics(
        inventory,
        compute.resource_id,
        start=start,
        end=start + timedelta(hours=3),
    )

    timestamps = {sample.timestamp for sample in samples}
    assert timestamps == {start, start + timedelta(hours=1), start + timedelta(hours=2)}
    assert {sample.name for sample in samples} == {
        "cpu_percent",
        "memory_percent",
        "network_out",
        "requests",
    }


def test_disk_has_no_utilization_series() -> None:
    inventory = seed_company()
    disk = _first(inventory, ResourceType.disk)

    assert query_metrics(inventory, disk.resource_id, start=history_start(), end=HISTORY_END) == []


def test_spike_trap_peak_diverges_from_average() -> None:
    inventory = seed_company()
    spike = _compute_with_profile(inventory, UsageProfile.spike_trap)
    steady = _compute_with_profile(inventory, UsageProfile.steady_mid)
    spike_avg, spike_peak = cpu_avg_and_peak(inventory, spike.resource_id)
    steady_avg, steady_peak = cpu_avg_and_peak(inventory, steady.resource_id)

    assert spike_peak > spike_avg * 3
    assert steady_peak < steady_avg * 1.6


def test_business_hours_are_busier_than_overnight() -> None:
    inventory = seed_company()
    resource = _compute_with_profile(inventory, UsageProfile.business_hours)
    wednesday = _at_weekday_hour(2, 15)
    sunday = _at_weekday_hour(6, 3)
    busy = query_metrics(
        inventory,
        resource.resource_id,
        start=wednesday,
        end=wednesday + timedelta(hours=1),
        name="cpu_percent",
    )
    quiet = query_metrics(
        inventory,
        resource.resource_id,
        start=sunday,
        end=sunday + timedelta(hours=1),
        name="cpu_percent",
    )

    assert busy[0].value > quiet[0].value * 3


def test_monthly_seasonality_moves_a_steady_series() -> None:
    inventory = seed_company()
    resource = _compute_with_profile(inventory, UsageProfile.steady_low)
    high = _window_mean(inventory, resource.resource_id, day=7)
    low = _window_mean(inventory, resource.resource_id, day=22)

    assert high > low


def test_unknown_resource_is_rejected() -> None:
    with pytest.raises(ValueError):
        query_metrics(seed_company(), "i-missing", start=history_start(), end=HISTORY_END)


def _first(inventory, resource_type):
    return next(item for item in inventory.resources if item.resource_type == resource_type)


def _compute_with_profile(inventory, profile: UsageProfile):
    return next(
        item
        for item in inventory.resources
        if item.resource_type == ResourceType.compute and usage_profile(item.resource_id) == profile
    )


def _at_weekday_hour(weekday: int, hour: int):
    cursor = history_start()
    while cursor.weekday() != weekday:
        cursor += timedelta(days=1)
    return cursor.replace(hour=hour)


def _window_mean(inventory, resource_id: str, day: int) -> float:
    start = history_start() + timedelta(days=day)
    samples = query_metrics(
        inventory,
        resource_id,
        start=start,
        end=start + timedelta(days=2),
        name="cpu_percent",
    )
    return sum(sample.value for sample in samples) / len(samples)
