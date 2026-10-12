from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.repositories import DependencyRepository, ResourceRepository
from app.schemas import Dependency, Resource


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


def test_dependency_lookup_returns_typed_edges(session: Session) -> None:
    resources = ResourceRepository(session)
    for resource_id in ("i-dep-app", "db-dep-1", "vol-dep-1", "bucket-dep-1"):
        resources.create(_resource(resource_id))
    DependencyRepository(session).upsert_many(
        [
            Dependency(
                source_resource_id="i-dep-app",
                target_resource_id="db-dep-1",
                relationship="uses_database",
            ),
            Dependency(
                source_resource_id="i-dep-app",
                target_resource_id="bucket-dep-1",
                relationship="reads_bucket",
            ),
            Dependency(
                source_resource_id="db-dep-1",
                target_resource_id="vol-dep-1",
                relationship="stores_on",
            ),
        ]
    )
    client = _client(session)

    dependencies = client.get("/resources/i-dep-app/dependencies")
    dependents = client.get("/resources/db-dep-1/dependents")
    stored_on = client.get("/resources/vol-dep-1/dependents")
    empty = client.get("/resources/bucket-dep-1/dependencies")
    missing = client.get("/resources/i-dep-missing/dependencies")

    assert dependencies.status_code == 200
    body = dependencies.json()
    assert body["resource_id"] == "i-dep-app"
    assert body["total"] == 2
    assert [(item["relationship"], item["target_resource_id"]) for item in body["items"]] == [
        ("reads_bucket", "bucket-dep-1"),
        ("uses_database", "db-dep-1"),
    ]
    assert dependents.status_code == 200
    assert dependents.json()["items"] == [
        {
            "source_resource_id": "i-dep-app",
            "target_resource_id": "db-dep-1",
            "relationship": "uses_database",
        }
    ]
    assert stored_on.json()["items"][0]["relationship"] == "stores_on"
    assert stored_on.json()["items"][0]["source_resource_id"] == "db-dep-1"
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0
    assert missing.status_code == 404


def _client(session: Session) -> TestClient:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def _resource(resource_id: str) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id="333333333333",
        environment="production",
        owner="payments",
        team="payments",
        business_criticality="high",
    )
