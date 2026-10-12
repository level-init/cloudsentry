"""Copy simulator metrics into daily rollups.

Hourly samples stay on the simulator. This job stores one row per resource,
metric name, and UTC day: the average and the peak of that day's samples.
Days are equal length, so a 30-day average is the mean of the daily averages
and the 30-day peak is the max of the daily peaks. Running the job again
updates those same days.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from sqlalchemy import select

from app.db import create_session
from app.repositories import MetricRollupRepository
from app.schemas import MetricRollup
from app.tables import ResourceRow
from worker.config import get_settings
from worker.inventory import fetch_resources, get_json

HISTORY_START = datetime(2025, 12, 2, tzinfo=timezone.utc)
_METRICS_TIMEOUT = 120


@dataclass(frozen=True)
class MetricIngestCounts:
    created: int
    updated: int
    rollups: int
    resources_with_series: int


def ingest_metrics(base_url: str | None = None) -> MetricIngestCounts:
    url = (base_url or get_settings().simulator_base_url).rstrip("/")
    end = _simulator_now(url)
    if end <= HISTORY_START:
        raise ValueError("simulator clock is before seeded history")
    resources = fetch_resources(url)
    session = create_session()
    try:
        known = set(session.scalars(select(ResourceRow.resource_id)))
        missing = [item["resource_id"] for item in resources if item["resource_id"] not in known]
        if missing:
            raise ValueError("run ingest-inventory before ingest-metrics")
        created = 0
        updated = 0
        rollups = 0
        with_series = 0
        for item in resources:
            resource_id = item["resource_id"]
            samples = fetch_metric_samples(url, resource_id, HISTORY_START, end)
            daily = daily_rollups(resource_id, samples)
            if not daily:
                continue
            with_series += 1
            chunk_created, chunk_updated = MetricRollupRepository(session).upsert_many(daily)
            created += chunk_created
            updated += chunk_updated
            rollups += len(daily)
            logging.info("metrics %s rollups=%s", resource_id, len(daily))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return MetricIngestCounts(created, updated, rollups, with_series)


def fetch_metric_samples(
    base_url: str,
    resource_id: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    query = urlencode(
        {
            "start": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    payload = get_json(
        f"{base_url}/resources/{resource_id}/metrics?{query}",
        timeout=_METRICS_TIMEOUT,
    )
    if not isinstance(payload, list):
        raise ValueError(f"metrics for {resource_id} were not a list")
    return payload


def daily_rollups(resource_id: str, samples: list[dict]) -> list[MetricRollup]:
    grouped: dict[tuple[str, date], list[float]] = {}
    units: dict[tuple[str, date], str] = {}
    for sample in samples:
        timestamp = datetime.fromisoformat(str(sample["timestamp"]).replace("Z", "+00:00"))
        key = (str(sample["name"]), timestamp.date())
        grouped.setdefault(key, []).append(float(sample["value"]))
        units[key] = str(sample["unit"])
    rollups: list[MetricRollup] = []
    for name, day in sorted(grouped):
        values = grouped[(name, day)]
        rollups.append(
            MetricRollup(
                resource_id=resource_id,
                name=name,
                day=day,
                avg_value=sum(values) / len(values),
                peak_value=max(values),
                unit=units[(name, day)],
            )
        )
    return rollups


def _simulator_now(base_url: str) -> datetime:
    payload = get_json(f"{base_url}/clock")
    return datetime.fromisoformat(str(payload["now"]).replace("Z", "+00:00"))
