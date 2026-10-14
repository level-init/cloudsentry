"""Recommend a weekday schedule for dev and staging compute that stays busy off hours.

The window is the 30 days ending the day after the latest cpu_percent rollup.
Saturday and Sunday are the off hours visible in daily rollups. A present
compute resource qualifies when its environment tag is development or staging,
the weekend average stays at or above 20, and the weekday average does too.
Production is out of scope. The recommendation is weekdays 09:00-17:00 UTC,
the same window the simulator calls weekdays-09-17.

i-dev-026 stays near 42% on weekends. A dev VM that drops off on weekends does
not get this finding.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.repositories import MetricRollupRepository
from app.schemas import Resource
from worker.detectors.idle import WINDOW_DAYS

SCHEDULE = "weekdays-09-17"
OFF_HOURS_AVG_MIN = 20.0
MIN_WEEKEND_DAYS = 8
MIN_WEEKDAY_DAYS = 20
_SCHEDULED_ENVIRONMENTS = frozenset({"development", "staging"})


class SchedulingDetector:
    name = "development_scheduling"

    def detect(self, resources: list[Resource], session: Session) -> list[Finding]:
        rollups = MetricRollupRepository(session)
        latest = rollups.latest_day("cpu_percent")
        if latest is None:
            return []
        end = latest + timedelta(days=1)
        start = end - timedelta(days=WINDOW_DAYS)
        candidates = [resource for resource in resources if _scheduled_environment(resource)]
        ids = [resource.resource_id for resource in candidates]
        days = rollups.daily_averages(ids, "cpu_percent", start, end)
        findings: list[Finding] = []
        for resource in candidates:
            split = _split(days.get(resource.resource_id, []))
            if split is None:
                continue
            weekday_avg, weekend_avg, weekday_days, weekend_days = split
            if weekend_avg < OFF_HOURS_AVG_MIN or weekday_avg < OFF_HOURS_AVG_MIN:
                continue
            if weekend_days < MIN_WEEKEND_DAYS or weekday_days < MIN_WEEKDAY_DAYS:
                continue
            environment = _environment(resource)
            findings.append(
                Finding(
                    finding_id=f"development_scheduling-{resource.resource_id}",
                    resource_ids=[resource.resource_id],
                    category="development_scheduling",
                    summary=(
                        f"{resource.resource_id} can run {SCHEDULE} "
                        f"instead of staying on through the weekend"
                    ),
                    evidence=[
                        f"environment {environment}",
                        f"weekday_cpu_avg {weekday_avg:.2f}",
                        f"weekend_cpu_avg {weekend_avg:.2f}",
                        f"schedule {SCHEDULE}",
                        "window weekdays 09:00-17:00 UTC",
                        f"tags {_tags(resource.tags)}",
                    ],
                )
            )
        return findings


def _scheduled_environment(resource: Resource) -> bool:
    if not resource.present or resource.resource_type != "compute":
        return False
    return _environment(resource) in _SCHEDULED_ENVIRONMENTS


def _environment(resource: Resource) -> str:
    tagged = resource.tags.get("environment")
    if tagged:
        return tagged
    return resource.environment.value


def _split(samples: list[tuple[date, float]]) -> tuple[float, float, int, int] | None:
    weekdays = [value for day, value in samples if day.weekday() < 5]
    weekends = [value for day, value in samples if day.weekday() >= 5]
    if not weekdays or not weekends:
        return None
    return (
        sum(weekdays) / len(weekdays),
        sum(weekends) / len(weekends),
        len(weekdays),
        len(weekends),
    )


def _tags(tags: dict[str, str]) -> str:
    return " ".join(f"{key}={tags[key]}" for key in sorted(tags))
