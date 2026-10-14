"""Idle compute: low CPU and low request traffic across a 30-day window.

The window ends the day after the latest stored cpu_percent rollup. A compute
resource is idle when that window has a full 30 days and every signal stays
under the cap: CPU average 15, CPU peak 25, request average 20, request peak
30. The planted idle VM i-dev-062 sits near 8% average and 12% peak. The
spike-trap i-prd-017 has a similar average and a peak of 100, so it is not idle.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.repositories import MetricRollupRepository
from app.schemas import Resource

WINDOW_DAYS = 30
CPU_AVG_MAX = 15.0
CPU_PEAK_MAX = 25.0
REQUEST_AVG_MAX = 20.0
REQUEST_PEAK_MAX = 30.0


class IdleComputeDetector:
    name = "idle_compute"

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
            if resource.present and resource.resource_type == "compute"
        ]
        ids = [resource.resource_id for resource in compute]
        cpu = rollups.window_summary(ids, "cpu_percent", start, end)
        requests = rollups.window_summary(ids, "requests", start, end)
        findings: list[Finding] = []
        for resource in compute:
            cpu_stats = cpu.get(resource.resource_id)
            request_stats = requests.get(resource.resource_id)
            if cpu_stats is None or request_stats is None:
                continue
            cpu_avg, cpu_peak, cpu_days = cpu_stats
            request_avg, request_peak, request_days = request_stats
            if cpu_days < WINDOW_DAYS or request_days < WINDOW_DAYS:
                continue
            if (
                cpu_avg >= CPU_AVG_MAX
                or cpu_peak >= CPU_PEAK_MAX
                or request_avg >= REQUEST_AVG_MAX
                or request_peak >= REQUEST_PEAK_MAX
            ):
                continue
            findings.append(
                Finding(
                    finding_id=f"idle_compute-{resource.resource_id}",
                    resource_ids=[resource.resource_id],
                    category="idle_compute",
                    summary=f"{resource.resource_id} is idle over {WINDOW_DAYS} days",
                    evidence=[
                        f"cpu_percent avg {cpu_avg:.2f}",
                        f"cpu_percent peak {cpu_peak:.2f}",
                        f"requests avg {request_avg:.2f}",
                        f"requests peak {request_peak:.2f}",
                        f"tags {_tags(resource.tags)}",
                    ],
                )
            )
        return findings


def _tags(tags: dict[str, str]) -> str:
    return " ".join(f"{key}={tags[key]}" for key in sorted(tags))
