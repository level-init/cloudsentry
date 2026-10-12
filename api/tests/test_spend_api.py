from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import get_session, sqlalchemy_database_url
from app.main import create_app
from app.repositories import CostRecordRepository, ResourceRepository
from app.schemas import CostRecord, Resource

_DEV_ACCOUNT = "888888888881"
_STAGE_ACCOUNT = "888888888882"


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


def test_spend_slices_match_the_sum_of_resource_costs(session: Session) -> None:
    resources = ResourceRepository(session)
    resources.create(_resource("i-spend-1", _DEV_ACCOUNT, "development"))
    resources.create(_resource("i-spend-2", _DEV_ACCOUNT, "development"))
    resources.create(_resource("i-spend-3", _STAGE_ACCOUNT, "staging"))
    costs = CostRecordRepository(session)
    costs.upsert_many(
        [
            _cost("i-spend-1", datetime(2026, 3, 1, tzinfo=UTC), 101),
            _cost("i-spend-2", datetime(2026, 3, 4, tzinfo=UTC), 202),
            _cost("i-spend-1", datetime(2026, 2, 1, tzinfo=UTC), 999),
            _cost("i-spend-3", datetime(2026, 3, 2, tzinfo=UTC), 50),
        ]
    )
    client = _client(session)

    accounts = client.get("/spend/accounts", params={"year": 2026, "month": 3})
    environments = client.get("/spend/environments", params={"year": 2026, "month": 3})
    february = client.get("/spend/accounts", params={"year": 2026, "month": 2})
    partial = client.get("/spend/accounts", params={"month": 3})

    by_account = costs.monthly_cents_by_account(2026, 3)
    by_environment = costs.monthly_cents_by_environment(2026, 3)
    development_ids = [
        resource.resource_id for resource in resources.list(environment="development")
    ]
    development_sum = sum(costs.monthly_cents_by_resource(2026, 3, development_ids).values())

    assert accounts.status_code == 200
    body = accounts.json()
    slices = {item["account_id"]: item["monthly_cost_cents"] for item in body["items"]}
    assert slices[_DEV_ACCOUNT] == 303
    assert slices[_STAGE_ACCOUNT] == 50
    assert slices[_DEV_ACCOUNT] == by_account[_DEV_ACCOUNT]
    assert body["total_cents"] == sum(item["monthly_cost_cents"] for item in body["items"])
    assert body["total_cents"] == sum(by_account.values())
    assert by_environment["development"] == development_sum
    assert sum(by_account.values()) == sum(by_environment.values())
    assert environments.status_code == 200
    env_body = environments.json()
    env_slices = {item["environment"]: item["monthly_cost_cents"] for item in env_body["items"]}
    assert env_slices["development"] == by_environment["development"]
    assert env_slices["staging"] == by_environment["staging"]
    assert env_body["total_cents"] == body["total_cents"]
    names = [item["environment"] for item in env_body["items"]]
    order = ["development", "staging", "production"]
    assert names == sorted(names, key=order.index)
    february_slices = {
        item["account_id"]: item["monthly_cost_cents"] for item in february.json()["items"]
    }
    assert february_slices[_DEV_ACCOUNT] == 999
    assert partial.status_code == 422


def _client(session: Session) -> TestClient:
    app = create_app()

    def override() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def _resource(resource_id: str, account_id: str, environment: str) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id=account_id,
        environment=environment,
        owner="payments",
        team="payments",
        business_criticality="low",
    )


def _cost(resource_id: str, start: datetime, cents: int) -> CostRecord:
    end = start.replace(day=start.day + 1)
    return CostRecord(
        resource_id=resource_id,
        period_start=start,
        period_end=end,
        amount=cents / 100,
        currency="USD",
    )
