"""Shared pytest helpers.

Tests use the same Postgres URL as the API/worker unless TEST_DATABASE_URL is
set. Fixtures wrap work in a rolled-back transaction, but committed inventory
from ingest or a live process is still visible. Prefer ensure_resource so seeds
do not UniqueViolation on those rows.
"""

from urllib.parse import urlparse

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import ResourceRepository
from app.schemas import Resource


def ensure_resource(session: Session, resource: Resource) -> None:
    """Insert or update a resource so seeds tolerate a shared Compose database."""
    ResourceRepository(session).upsert(resource)


def simulator_request(client: TestClient):
    """Translate adapter HTTP calls onto an in-process simulator TestClient."""

    def request(method: str, url: str, body: dict | None) -> tuple[int, object]:
        parsed = urlparse(url)
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        if method == "GET":
            response = client.get(path)
        else:
            response = client.request(method, path, json=body)
        if not response.content:
            return response.status_code, None
        return response.status_code, response.json()

    return request
