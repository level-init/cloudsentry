"""Recommend the next smaller compute SKU when the peak still fits.

The ladder is t3.medium, then m5.large, then m5.xlarge. Each step has twice
the capacity of the one below it. A recommendation moves one step down, never
two. The projected peak on that next size is the current peak times the
capacity ratio. It must stay under (1 - headroom) * 100. The average must
also stay under rightsizing_avg_max. Headroom defaults to 0.5, so the
projected peak must stay under 50.

i-prd-013 is an m5.xlarge with a peak near 12, so the next size is m5.large.
i-prd-017 has a peak of 100. Projecting that onto m5.large is 200, and onto
t3.medium is 400, so it is not offered a two-step drop.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.repositories import MetricRollupRepository
from app.schemas import Resource
from worker.config import get_settings
from worker.detectors.idle import WINDOW_DAYS

_LADDER = ("t3.medium", "m5.large", "m5.xlarge")
_CAPACITY = {"t3.medium": 1, "m5.large": 2, "m5.xlarge": 4}


class RightsizingDetector:
    name = "compute_rightsizing"

    def __init__(self, headroom: float | None = None, avg_max: float | None = None) -> None:
        settings = get_settings()
        self.headroom = settings.rightsizing_headroom if headroom is None else headroom
        self.avg_max = settings.rightsizing_avg_max if avg_max is None else avg_max

    def detect(self, resources: list[Resource], session: Session) -> list[Finding]:
        rollups = MetricRollupRepository(session)
        latest = rollups.latest_day("cpu_percent")
        if latest is None:
            return []
        end = latest + timedelta(days=1)
        start = end - timedelta(days=WINDOW_DAYS)
        compute = [
            resource
            for resource in resources
            if resource.present and resource.resource_type == "compute" and resource.sku
        ]
        ids = [resource.resource_id for resource in compute]
        cpu = rollups.window_summary(ids, "cpu_percent", start, end)
        findings: list[Finding] = []
        for resource in compute:
            stats = cpu.get(resource.resource_id)
            if stats is None:
                continue
            cpu_avg, cpu_peak, days = stats
            if days < WINDOW_DAYS:
                continue
            target = next_sku(
                resource.sku or "",
                cpu_avg,
                cpu_peak,
                headroom=self.headroom,
                avg_max=self.avg_max,
            )
            if target is None:
                continue
            projected = projected_peak(resource.sku or "", target, cpu_peak)
            findings.append(
                Finding(
                    finding_id=f"compute_rightsizing-{resource.resource_id}",
                    resource_ids=[resource.resource_id],
                    category="compute_rightsizing",
                    summary=f"{resource.resource_id} can move from {resource.sku} to {target}",
                    evidence=[
                        f"cpu_percent avg {cpu_avg:.2f}",
                        f"cpu_percent peak {cpu_peak:.2f}",
                        f"current_sku {resource.sku}",
                        f"recommended_sku {target}",
                        f"projected_peak {projected:.2f}",
                        f"headroom {self.headroom:.2f}",
                        f"tags {_tags(resource.tags)}",
                    ],
                )
            )
        return findings


def next_sku(
    current: str,
    cpu_avg: float,
    cpu_peak: float,
    *,
    headroom: float,
    avg_max: float,
) -> str | None:
    if current not in _CAPACITY or cpu_avg >= avg_max:
        return None
    index = _LADDER.index(current)
    if index == 0:
        return None
    target = _LADDER[index - 1]
    if projected_peak(current, target, cpu_peak) >= (1 - headroom) * 100:
        return None
    return target


def projected_peak(current: str, target: str, cpu_peak: float) -> float:
    return cpu_peak * _CAPACITY[current] / _CAPACITY[target]


def veto_sku(
    current: str,
    cpu_avg: float,
    cpu_peak: float,
    *,
    headroom: float,
    avg_max: float,
) -> str | None:
    """The next smaller sku when the average looks safe and the peak does not fit.

    A spike such as i-prd-017 has a low average, so a one-step resize looks
    tempting, but the projected peak is over the headroom cap. That sku is
    rejected instead of recommended. The smallest sku has no smaller step.
    """
    if next_sku(current, cpu_avg, cpu_peak, headroom=headroom, avg_max=avg_max) is not None:
        return None
    if current not in _CAPACITY or cpu_avg >= avg_max:
        return None
    index = _LADDER.index(current)
    if index == 0:
        return None
    target = _LADDER[index - 1]
    if projected_peak(current, target, cpu_peak) < (1 - headroom) * 100:
        return None
    return target


def two_step_sku(current: str) -> str | None:
    if current not in _CAPACITY:
        return None
    index = _LADDER.index(current)
    if index < 2:
        return None
    return _LADDER[index - 2]


def _tags(tags: dict[str, str]) -> str:
    return " ".join(f"{key}={tags[key]}" for key in sorted(tags))
