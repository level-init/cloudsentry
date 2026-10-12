from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.repositories import CostRecordRepository, MetricRollupRepository, ResourceRepository
from app.schemas import CostRecord, MetricRollup, Resource


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


def test_list_and_get_include_cost_and_utilization(session: Session) -> None:
    _seed(session)
    client = _client(session)

    listed = client.get(
        "/resources",
        params={
            "account_id": "111111111111",
            "environment": "development",
            "resource_type": "compute",
            "year": 2026,
            "month": 3,
        },
    )
    idle = client.get("/resources/i-api-idle", params={"year": 2026, "month": 3})
    disk = client.get("/resources/i-api-disk", params={"year": 2026, "month": 3})
    missing = client.get("/resources/i-api-missing")
    partial = client.get("/resources", params={"year": 2026})

    assert listed.status_code == 200
    body = listed.json()
    ids = [item["resource_id"] for item in body["items"]]
    assert body["total"] == len(body["items"])
    assert "i-api-idle" in ids
    assert "i-api-disk" not in ids
    assert "i-api-prod" not in ids
    assert all(item["environment"] == "development" for item in body["items"])
    assert all(item["resource_type"] == "compute" for item in body["items"])
    match = next(item for item in body["items"] if item["resource_id"] == "i-api-idle")
    assert match["monthly_cost_cents"] == 3037
    assert match["cpu_avg"] == 8.0
    assert match["cpu_peak"] == 12.0
    assert match["year"] == 2026
    assert match["month"] == 3
    assert idle.status_code == 200
    assert idle.json() == match
    assert disk.status_code == 200
    assert disk.json()["monthly_cost_cents"] == 500
    assert disk.json()["cpu_avg"] is None
    assert disk.json()["cpu_peak"] is None
    assert missing.status_code == 404
    assert partial.status_code == 422


def test_omitted_month_uses_the_latest_cost_month(session: Session) -> None:
    ResourceRepository(session).create(_resource("i-api-later", "compute", "111111111111"))
    CostRecordRepository(session).upsert_many(
        [
            CostRecord(
                resource_id="i-api-later",
                period_start=datetime(2099, 1, 15, tzinfo=UTC),
                period_end=datetime(2099, 1, 16, tzinfo=UTC),
                amount=2.5,
                currency="USD",
            )
        ]
    )
    client = _client(session)

    response = client.get("/resources/i-api-later")

    assert response.status_code == 200
    assert response.json()["year"] == 2099
    assert response.json()["month"] == 1
    assert response.json()["monthly_cost_cents"] == 250
    assert response.json()["cpu_avg"] is None


def _client(session: Session) -> TestClient:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def _seed(session: Session) -> None:
    resources = ResourceRepository(session)
    resources.create(_resource("i-api-idle", "compute", "111111111111"))
    resources.create(_resource("i-api-disk", "disk", "111111111111"))
    resources.create(_resource("i-api-prod", "compute", "333333333333", "production"))
    CostRecordRepository(session).upsert_many(
        [
            _cost("i-api-idle", 3037),
            _cost("i-api-disk", 500),
        ]
    )
    MetricRollupRepository(session).upsert_many(
        [
            MetricRollup(
                resource_id="i-api-idle",
                name="cpu_percent",
                day=date(2026, 3, 2),
                avg_value=8.0,
                peak_value=12.0,
                unit="percent",
            )
        ]
    )


def _resource(
    resource_id: str,
    resource_type: str,
    account_id: str,
    environment: str = "development",
) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type=resource_type,
        account_id=account_id,
        environment=environment,
        owner="payments",
        team="payments",
        business_criticality="low",
    )


def _cost(resource_id: str, cents: int) -> CostRecord:
    return CostRecord(
        resource_id=resource_id,
        period_start=datetime(2026, 3, 1, tzinfo=UTC),
        period_end=datetime(2026, 3, 2, tzinfo=UTC),
        amount=cents / 100,
        currency="USD",
    )
