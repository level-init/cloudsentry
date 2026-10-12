"""Copy simulator billing into cost records.

Each simulator daily line becomes one cost row. The amount is dollars, converted
from integer cents. The monthly helper adds those rows back up in cents, so a
full month matches the simulator total. Days after the simulator clock are not
returned, and a second run updates the same resource and period.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db import create_session
from app.repositories import CostRecordRepository
from app.schemas import CostRecord
from app.tables import ResourceRow
from worker.config import get_settings
from worker.inventory import fetch_resources, get_json

_FIRST_BILLED_MONTH = (2025, 12)


@dataclass(frozen=True)
class BillingIngestCounts:
    created: int
    updated: int
    records: int


def ingest_billing(base_url: str | None = None) -> BillingIngestCounts:
    url = (base_url or get_settings().simulator_base_url).rstrip("/")
    observed = _last_observed_day(_simulator_now(url))
    months = _months_through(observed)
    resources = fetch_resources(url)
    session = create_session()
    try:
        known = set(session.scalars(select(ResourceRow.resource_id)))
        missing = [item["resource_id"] for item in resources if item["resource_id"] not in known]
        if missing:
            raise ValueError("run ingest-inventory before ingest-billing")
        created = 0
        updated = 0
        records = 0
        for item in resources:
            resource_id = item["resource_id"]
            daily: list[CostRecord] = []
            for year, month in months:
                report = get_json(f"{url}/resources/{resource_id}/costs?year={year}&month={month}")
                daily.extend(records_from_report(report))
            if not daily:
                continue
            chunk_created, chunk_updated = CostRecordRepository(session).upsert_many(daily)
            created += chunk_created
            updated += chunk_updated
            records += len(daily)
            logging.info("billing %s records=%s", resource_id, len(daily))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return BillingIngestCounts(created, updated, records)


def records_from_report(report: dict) -> list[CostRecord]:
    records: list[CostRecord] = []
    for line in report["lines"]:
        day = date.fromisoformat(line["day"])
        period_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        cents = int(line["amount_cents"])
        records.append(
            CostRecord(
                resource_id=line["resource_id"],
                period_start=period_start,
                period_end=period_start + timedelta(days=1),
                amount=cents / 100,
                currency=line["currency"],
            )
        )
    return records


def _months_through(last: date) -> list[tuple[int, int]]:
    year, month = _FIRST_BILLED_MONTH
    months: list[tuple[int, int]] = []
    while (year, month) <= (last.year, last.month):
        months.append((year, month))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return months


def _last_observed_day(now: datetime) -> date:
    return now.date() - timedelta(days=1)


def _simulator_now(base_url: str) -> datetime:
    payload = get_json(f"{base_url}/clock")
    return datetime.fromisoformat(str(payload["now"]).replace("Z", "+00:00"))
