import json
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import ResourceRepository
from worker.inventory import fetch_resources, ingest_resources, resource_from_simulator


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(sqlalchemy_database_url())
    try:
        connection = engine.connect()
    except Exception as exc:
        pytest.skip(f"Postgres is not available: {exc}")
    transaction = connection.begin()
    bound = Session(bind=connection)
    try:
        yield bound
    finally:
        bound.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


def test_fetch_follows_pages() -> None:
    pages = [_payload("i-a"), _payload("i-b")]
    with _server(pages) as base_url:
        fetched = fetch_resources(base_url, page_size=1)

    assert [item["resource_id"] for item in fetched] == ["i-a", "i-b"]


def test_mapping_uses_owner_team_and_criticality_tags() -> None:
    resource = resource_from_simulator(_payload("i-a"))

    assert resource.owner == "payments-dev"
    assert resource.team == "payments"
    assert resource.business_criticality == "low"
    assert resource.tags["criticality"] == "low"
    assert "sku" not in resource.model_dump()


def test_missing_criticality_tag_is_rejected() -> None:
    payload = _payload("i-a")
    del payload["tags"]["criticality"]

    with pytest.raises(ValueError, match="criticality"):
        resource_from_simulator(payload)


def test_second_ingest_updates_instead_of_inserting(session: Session) -> None:
    resources = [resource_from_simulator(_payload("i-ingest-1"))]
    first = ingest_resources(session, resources)
    changed = resources[0].model_copy(update={"owner": "platform"})
    second = ingest_resources(session, [changed])
    stored = [
        resource
        for resource in ResourceRepository(session).list()
        if resource.resource_id == "i-ingest-1"
    ]

    assert first.created == 1 and first.updated == 0
    assert second.created == 0 and second.updated == 1
    assert len(stored) == 1
    assert stored[0].owner == "platform"


def _payload(resource_id: str) -> dict:
    return {
        "resource_id": resource_id,
        "resource_type": "compute",
        "account_id": "111111111111",
        "environment": "development",
        "name": resource_id,
        "tags": {
            "owner": "payments-dev",
            "team": "payments",
            "environment": "development",
            "criticality": "low",
        },
        "sku": "t3.medium",
    }


class _Pages:
    def __init__(self, items: list[dict], base_url: str) -> None:
        self.items = items
        self.base_url = base_url
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def __enter__(self) -> str:
        items = self.items

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                query = parse_qs(urlparse(self.path).query)
                offset = int(query["offset"][0])
                limit = int(query["limit"][0])
                batch = items[offset : offset + limit]
                body = json.dumps(
                    {"items": batch, "total": len(items), "limit": limit, "offset": offset}
                ).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._httpd.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *exc) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()


def _server(items: list[dict]) -> _Pages:
    return _Pages(items, "")
