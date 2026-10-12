from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import CostRecordRepository, ResourceRepository
from app.schemas import Resource
from worker.billing_ingest import records_from_report

_ACCOUNT = "999999999999"


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


def test_monthly_cents_match_the_simulator_lines(session: Session) -> None:
    resources = ResourceRepository(session)
    resources.create(_resource("i-bill-1"))
    resources.create(_resource("i-bill-2"))
    records = records_from_report(
        {
            "lines": [
                _line("i-bill-1", "2026-03-01", 452),
                _line("i-bill-1", "2026-03-02", 100),
                _line("i-bill-2", "2026-03-01", 50),
            ]
        }
    )
    costs = CostRecordRepository(session)
    created, updated = costs.upsert_many(records)
    again_created, again_updated = costs.upsert_many(records)

    assert created == 3 and updated == 0
    assert costs.monthly_cents(2026, 3, resource_id="i-bill-1") == 552
    assert costs.monthly_cents(2026, 3, account_id=_ACCOUNT) == 602
    assert again_created == 0 and again_updated == 3
    assert costs.count("i-bill-1") == 2


def _resource(resource_id: str) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id=_ACCOUNT,
        environment="development",
        owner="payments",
        team="payments",
        business_criticality="low",
        tags={"criticality": "low"},
    )


def _line(resource_id: str, day: str, amount_cents: int) -> dict:
    return {
        "resource_id": resource_id,
        "day": day,
        "amount_cents": amount_cents,
        "currency": "USD",
    }
