"""Propose lifecycle rules for expensive standard storage and old large snapshots.

Object storage on the standard tier is a candidate when its latest month costs
at least lifecycle_cost_cents. The default is 5000, so s3-standard-5tb matches
and s3-standard-500gb does not. The action is transition-to-infrequent-access.
A bucket already on infrequent_access is skipped. Request average over the
latest 30 days is the access-pattern proxy in the evidence.

A non-production snapshot is a retention candidate when it costs at least that
same amount and its cost history is at least lifecycle_retention_days old.
The default is 90. The action is expire-after that many days. Production
snapshots are left alone. snap-dev-007 and bucket-prd-022 are the planted
fixtures.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.repositories import CostRecordRepository, DependencyRepository, MetricRollupRepository
from app.schemas import Resource
from worker.config import get_settings
from worker.detectors.idle import WINDOW_DAYS

_OBJECT_STORAGE = "object_storage"
_SNAPSHOT = "snapshot"
_TRANSITION = "transition-to-infrequent-access"


class LifecycleDetector:
    name = "storage_lifecycle"

    def __init__(self, cost_cents: int | None = None, retention_days: int | None = None) -> None:
        settings = get_settings()
        self.cost_cents = settings.lifecycle_cost_cents if cost_cents is None else cost_cents
        self.retention_days = (
            settings.lifecycle_retention_days if retention_days is None else retention_days
        )

    def detect(self, resources: list[Resource], session: Session) -> list[Finding]:
        candidates = [resource for resource in resources if _candidate(resource)]
        ids = [resource.resource_id for resource in candidates]
        costs = CostRecordRepository(session).age_and_latest_month_cents(ids)
        attached = DependencyRepository(session).targets_with_dependents(ids)
        requests = _request_averages(session, candidates)
        findings: list[Finding] = []
        for resource in candidates:
            summary = costs.get(resource.resource_id)
            if summary is None:
                continue
            age_days, month_cents = summary
            if month_cents < self.cost_cents:
                continue
            tier = _tier(resource)
            if resource.resource_type == _OBJECT_STORAGE:
                if tier != "standard":
                    continue
                action = _TRANSITION
                access = requests.get(resource.resource_id, "none")
            else:
                if age_days < self.retention_days or resource.resource_id in attached:
                    continue
                action = f"expire-after-{self.retention_days}-days"
                access = "unused"
            findings.append(
                Finding(
                    finding_id=f"storage_lifecycle-{resource.resource_id}",
                    resource_ids=[resource.resource_id],
                    category="storage_lifecycle",
                    summary=f"{resource.resource_id} can use {action}",
                    evidence=[
                        f"current_tier {tier}",
                        f"access_proxy {access}",
                        f"monthly_cost_cents {month_cents}",
                        f"action {action}",
                        f"tags {_tags(resource.tags)}",
                    ],
                )
            )
        return findings


def _candidate(resource: Resource) -> bool:
    if not resource.present:
        return False
    if resource.resource_type == _OBJECT_STORAGE:
        return True
    return resource.resource_type == _SNAPSHOT and resource.environment.value != "production"


def _tier(resource: Resource) -> str:
    if resource.storage_class:
        return resource.storage_class
    if resource.sku and resource.sku.startswith("s3-standard"):
        return "standard"
    return resource.sku or "unknown"


def _request_averages(session: Session, resources: list[Resource]) -> dict[str, str]:
    buckets = [
        resource.resource_id for resource in resources if resource.resource_type == _OBJECT_STORAGE
    ]
    if not buckets:
        return {}
    rollups = MetricRollupRepository(session)
    latest = rollups.latest_day("requests")
    if latest is None:
        return {}
    end = latest + timedelta(days=1)
    start = end - timedelta(days=WINDOW_DAYS)
    stats = rollups.window_summary(buckets, "requests", start, end)
    return {
        resource_id: f"requests_avg {average:.2f}"
        for resource_id, (average, _peak, _days) in stats.items()
    }


def _tags(tags: dict[str, str]) -> str:
    return " ".join(f"{key}={tags[key]}" for key in sorted(tags))
