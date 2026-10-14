"""Find unattached disks and old unused snapshots.

A disk is unattached when nothing depends on it. A snapshot is unused when
nothing depends on it. Both must be at least storage_age_days old, counted
from the first cost row to the last. The default is 30 days. Evidence
includes the attach state, that age, and the latest month's cost in cents.

Production snapshots are out of scope. vol-dev-042 is the planted unattached
disk. snap-dev-007 is an old development snapshot with nothing depending on it.
"""

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.repositories import CostRecordRepository, DependencyRepository
from app.schemas import Resource
from worker.config import get_settings

_DISK = "disk"
_SNAPSHOT = "snapshot"


class UnattachedStorageDetector:
    name = "unattached_storage"

    def __init__(self, age_days: int | None = None) -> None:
        settings = get_settings()
        self.age_days = settings.storage_age_days if age_days is None else age_days

    def detect(self, resources: list[Resource], session: Session) -> list[Finding]:
        candidates = [resource for resource in resources if _candidate(resource)]
        ids = [resource.resource_id for resource in candidates]
        attached = DependencyRepository(session).targets_with_dependents(ids)
        costs = CostRecordRepository(session).age_and_latest_month_cents(ids)
        findings: list[Finding] = []
        for resource in candidates:
            if resource.resource_id in attached:
                continue
            summary = costs.get(resource.resource_id)
            if summary is None:
                continue
            age_days, month_cents = summary
            if age_days < self.age_days:
                continue
            state = "unattached" if resource.resource_type == _DISK else "unused"
            findings.append(
                Finding(
                    finding_id=f"unattached_storage-{resource.resource_id}",
                    resource_ids=[resource.resource_id],
                    category="unattached_storage",
                    summary=f"{resource.resource_id} is {state} and {age_days} days old",
                    evidence=[
                        f"attach_state {state}",
                        f"age_days {age_days}",
                        f"monthly_cost_cents {month_cents}",
                        f"resource_type {resource.resource_type}",
                        f"tags {_tags(resource.tags)}",
                    ],
                )
            )
        return findings


def _candidate(resource: Resource) -> bool:
    if not resource.present:
        return False
    if resource.resource_type == _DISK:
        return True
    if resource.resource_type == _SNAPSHOT and resource.environment.value != "production":
        return True
    return False


def _tags(tags: dict[str, str]) -> str:
    return " ".join(f"{key}={tags[key]}" for key in sorted(tags))
