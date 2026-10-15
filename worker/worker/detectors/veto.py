"""Reject a rightsizing step whose projected peak does not fit.

compute_rightsizing stays silent when the next sku is unsafe. This detector
records that refusal so planning can store a REJECTED proposal. i-prd-017 is
the planted case: the average is about 7, the peak is 100, m5.large would
project 200, and t3.medium would project 400.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.repositories import MetricRollupRepository
from app.schemas import Resource
from worker.config import get_settings
from worker.detectors.idle import WINDOW_DAYS
from worker.detectors.rightsizing import projected_peak, two_step_sku, veto_sku


class RightsizingVetoDetector:
    name = "rightsizing_veto"

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
            sku = resource.sku or ""
            rejected = veto_sku(
                sku,
                cpu_avg,
                cpu_peak,
                headroom=self.headroom,
                avg_max=self.avg_max,
            )
            if rejected is None:
                continue
            projected = projected_peak(sku, rejected, cpu_peak)
            smaller = two_step_sku(sku)
            evidence = [
                f"cpu_percent avg {cpu_avg:.2f}",
                f"cpu_percent peak {cpu_peak:.2f}",
                f"current_sku {sku}",
                f"rejected_sku {rejected}",
                f"projected_peak {projected:.2f}",
            ]
            if smaller is not None:
                evidence.append(f"two_step_sku {smaller}")
                evidence.append(
                    f"two_step_projected_peak {projected_peak(sku, smaller, cpu_peak):.2f}"
                )
            evidence.append(f"tags {_tags(resource.tags)}")
            findings.append(
                Finding(
                    finding_id=f"rightsizing_veto-{resource.resource_id}",
                    resource_ids=[resource.resource_id],
                    category="rightsizing_veto",
                    summary=f"do not resize {resource.resource_id} from {sku} to {rejected}",
                    evidence=evidence,
                )
            )
        return findings


def _tags(tags: dict[str, str]) -> str:
    return " ".join(f"{key}={tags[key]}" for key in sorted(tags))
