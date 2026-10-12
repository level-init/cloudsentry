"""Copy simulator inventory into the resources table.

One database row per resource returned by GET /resources. owner, team, and
business_criticality are the owner, team, and criticality tags. Simulator
fields that are not columns (name, sku, power_state, schedule, storage_class)
are left behind. Metrics and billing are not ingested. A second run updates
the same resource ids. A resource missing from that full list is marked
present=false and kept, along with its history.
"""

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from sqlalchemy.orm import Session

from app.db import create_session
from app.repositories import ResourceRepository
from app.schemas import Resource
from worker.config import get_settings

_PAGE_SIZE = 200


@dataclass(frozen=True)
class IngestCounts:
    created: int
    updated: int
    total: int
    absent: int


def ingest_inventory(base_url: str | None = None) -> IngestCounts:
    settings = get_settings()
    url = (base_url or settings.simulator_base_url).rstrip("/")
    resources = [resource_from_simulator(item) for item in fetch_resources(url)]
    session = create_session()
    try:
        counts = ingest_resources(session, resources)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return counts


def ingest_resources(session: Session, resources: list[Resource]) -> IngestCounts:
    repository = ResourceRepository(session)
    created = 0
    for resource in resources:
        if repository.upsert(resource):
            created += 1
    total = len(resources)
    absent = repository.mark_absent({resource.resource_id for resource in resources})
    return IngestCounts(created=created, updated=total - created, total=total, absent=absent)


def fetch_resources(base_url: str, *, page_size: int = _PAGE_SIZE) -> list[dict]:
    items: list[dict] = []
    offset = 0
    total: int | None = None
    while total is None or offset < total:
        page = get_json(f"{base_url}/resources?limit={page_size}&offset={offset}")
        batch = page["items"]
        total = int(page["total"])
        if not batch:
            break
        items.extend(batch)
        offset += len(batch)
    if total is None or len(items) != total:
        raise ValueError(f"simulator returned {len(items)} resources, total was {total}")
    return items


def resource_from_simulator(payload: dict) -> Resource:
    tags = payload.get("tags") or {}
    resource_id = payload["resource_id"]
    missing = [name for name in ("owner", "team", "criticality") if name not in tags]
    if missing:
        raise ValueError(f"{resource_id} is missing tags: {', '.join(missing)}")
    return Resource(
        resource_id=resource_id,
        resource_type=payload["resource_type"],
        account_id=payload["account_id"],
        environment=payload["environment"],
        owner=tags["owner"],
        team=tags["team"],
        business_criticality=tags["criticality"],
        tags=tags,
    )


def get_json(url: str, *, timeout: int = 30) -> dict:
    try:
        with urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ValueError(f"simulator request failed for {url}") from exc
