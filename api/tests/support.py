"""Shared pytest helpers.

Tests use the same Postgres URL as the API/worker unless TEST_DATABASE_URL is
set. Fixtures wrap work in a rolled-back transaction, but committed inventory
from ingest or a live process is still visible. Prefer ensure_resource so seeds
do not UniqueViolation on those rows.
"""

from sqlalchemy.orm import Session

from app.repositories import ResourceRepository
from app.schemas import Resource


def ensure_resource(session: Session, resource: Resource) -> None:
    """Insert or update a resource so seeds tolerate a shared Compose database."""
    ResourceRepository(session).upsert(resource)
