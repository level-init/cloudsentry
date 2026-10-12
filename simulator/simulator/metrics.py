"""Deterministic hourly utilization for the seeded company.

Samples are generated from the resource id, its current power state and
schedule, and the timestamp. The same state and window always return the same
series. Stopped compute is flat at zero. A weekday schedule is zero outside
09:00-17:00 UTC on weekdays. Changing the SKU does not rewrite utilization.
This is not CloudWatch.
"""

import hashlib
import math
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from simulator.model import Inventory, ResourceType, SimResource
from simulator.seed import seed_company

HISTORY_DAYS = 120
HISTORY_END = datetime(2026, 4, 1, tzinfo=timezone.utc)

_SERIES: dict[ResourceType, tuple[tuple[str, str], ...]] = {
    ResourceType.compute: (
        ("cpu_percent", "percent"),
        ("memory_percent", "percent"),
        ("network_out", "bytes"),
        ("requests", "count"),
    ),
    ResourceType.database: (
        ("cpu_percent", "percent"),
        ("memory_percent", "percent"),
        ("connections", "count"),
    ),
    ResourceType.load_balancer: (
        ("requests", "count"),
        ("network_out", "bytes"),
    ),
    ResourceType.cluster: (
        ("cpu_percent", "percent"),
        ("memory_percent", "percent"),
    ),
    ResourceType.object_storage: (("requests", "count"),),
}


class UsageProfile(StrEnum):
    steady_low = "steady_low"
    steady_mid = "steady_mid"
    business_hours = "business_hours"
    spike_trap = "spike_trap"


class MetricSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    timestamp: datetime
    value: float
    unit: str = Field(min_length=1)


def history_start() -> datetime:
    return HISTORY_END - timedelta(days=HISTORY_DAYS)


def usage_profile(resource_id: str) -> UsageProfile:
    digest = hashlib.sha256(resource_id.encode()).digest()
    profiles = list(UsageProfile)
    return profiles[digest[0] % len(profiles)]


def query_metrics(
    inventory: Inventory,
    resource_id: str,
    *,
    start: datetime,
    end: datetime,
    name: str | None = None,
) -> list[MetricSample]:
    resource = next((item for item in inventory.resources if item.resource_id == resource_id), None)
    if resource is None:
        raise ValueError(f"unknown resource {resource_id}")
    _require_utc(start)
    _require_utc(end)
    if end <= start:
        raise ValueError("end must be after start")
    series = _SERIES.get(resource.resource_type, ())
    selected = series if name is None else tuple(item for item in series if item[0] == name)
    if name is not None and not selected:
        raise ValueError(f"{resource.resource_type} has no {name} series")
    samples: list[MetricSample] = []
    hour = _first_hour(start)
    while hour < end:
        for metric_name, unit in selected:
            samples.append(
                MetricSample(
                    resource_id=resource_id,
                    name=metric_name,
                    timestamp=hour,
                    value=_value(resource, metric_name, hour),
                    unit=unit,
                )
            )
        hour += timedelta(hours=1)
    return samples


def cpu_avg_and_peak(inventory: Inventory, resource_id: str) -> tuple[float, float]:
    samples = query_metrics(
        inventory,
        resource_id,
        start=history_start(),
        end=HISTORY_END,
        name="cpu_percent",
    )
    values = [sample.value for sample in samples]
    return sum(values) / len(values), max(values)


def main() -> None:
    inventory = seed_company()
    examples: dict[UsageProfile, str] = {}
    for resource in inventory.resources:
        if resource.resource_type != ResourceType.compute:
            continue
        profile = usage_profile(resource.resource_id)
        examples.setdefault(profile, resource.resource_id)
    window = f"{history_start().date()} .. {HISTORY_END.date()}"
    print(f"history: {window} ({HISTORY_DAYS} days, hourly)")
    for profile in (UsageProfile.spike_trap, UsageProfile.steady_mid):
        resource_id = examples[profile]
        average, peak = cpu_avg_and_peak(inventory, resource_id)
        print(f"{resource_id} {profile}: avg {average:.1f}% peak {peak:.1f}%")


def _value(resource: SimResource, name: str, hour: datetime) -> float:
    level = _activity(resource, hour)
    if name == "cpu_percent":
        return round(level, 2)
    if name == "memory_percent":
        return round(min(100.0, level * 0.85), 2)
    if name == "network_out":
        return round(level / 100 * 5_000_000, 2)
    if name == "requests":
        return round(level * 1.5, 2)
    if name == "connections":
        return round(level * 0.4, 2)
    raise ValueError(f"unknown metric {name}")


def _activity(resource: SimResource, hour: datetime) -> float:
    if resource.power_state == "stopped":
        return 0.0
    resource_id = resource.resource_id
    if resource.schedule == "weekdays-09-17" and not _on_schedule(hour):
        return 0.0
    profile = usage_profile(resource_id)
    weekday = hour.weekday() < 5
    business = weekday and 9 <= hour.hour < 17
    if profile == UsageProfile.steady_low:
        level = 8.0
    elif profile == UsageProfile.steady_mid:
        level = 42.0
    elif profile == UsageProfile.business_hours:
        level = 72.0 if business else 6.0
    else:
        level = 92.0 if hour.weekday() == 2 and hour.hour == 15 else 7.0
    day_index = (hour - history_start()).days
    season = 1 + 0.12 * math.sin(2 * math.pi * day_index / 30)
    noise = (_unit_noise(resource_id, hour) - 0.5) * 6
    return min(100.0, max(0.0, level * season + noise))


def _on_schedule(hour: datetime) -> bool:
    return hour.weekday() < 5 and 9 <= hour.hour < 17


def _unit_noise(resource_id: str, hour: datetime) -> float:
    digest = hashlib.sha256(f"{resource_id}:{hour.isoformat()}".encode()).digest()
    return digest[1] / 255


def _first_hour(start: datetime) -> datetime:
    hour = start.replace(minute=0, second=0, microsecond=0)
    if hour < start:
        return hour + timedelta(hours=1)
    return hour


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC")


if __name__ == "__main__":
    main()
