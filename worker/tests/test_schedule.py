import logging
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import DetectionRunRepository, FindingRepository, ResourceRepository
from app.schemas import Resource
from app.tables import FindingRow
from worker.config import get_settings
from worker.detectors.registry import DetectorRegistry
from worker.detectors.sample import SampleDetector
from worker.schedule import run_once

_FINDING = "sample-i-sched-sample"


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


def test_manual_and_scheduled_runs_are_recorded_without_duplicate_findings(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    ResourceRepository(session).create(
        Resource(
            resource_id="i-sched-sample",
            resource_type="compute",
            account_id="111111111111",
            environment="development",
            owner="payments",
            team="payments",
            business_criticality="low",
            tags={"scenario": "sample"},
        )
    )
    registry = DetectorRegistry()
    registry.register(SampleDetector())

    scheduled = run_once(session, "schedule", registry)
    manual = run_once(session, "manual", registry, interval_seconds=120)
    again = run_once(session, "schedule", registry)

    assert scheduled.run.trigger == "schedule"
    assert scheduled.run.interval_seconds == get_settings().detection_interval_seconds
    assert scheduled.run.finished_at >= scheduled.run.started_at
    assert scheduled.run.created == 1
    assert scheduled.run.findings == 1
    planted = _one(scheduled.result.findings)
    assert DetectionRunRepository(session).get(scheduled.run.run_id) == scheduled.run

    assert manual.run.trigger == "manual"
    assert manual.run.interval_seconds == 120
    assert manual.run.run_id != scheduled.run.run_id
    assert manual.run.created == 0
    assert manual.run.updated == 1

    assert again.run.trigger == "schedule"
    assert again.run.created == 0
    assert again.run.updated == 1
    assert again.run.run_id not in {scheduled.run.run_id, manual.run.run_id}
    assert FindingRepository(session).get(_FINDING) == planted
    stored = session.scalar(
        select(func.count()).select_from(FindingRow).where(FindingRow.finding_id == _FINDING)
    )
    assert stored == 1
    assert "detect started trigger=schedule" in caplog.text
    assert f"detect finished trigger=schedule run_id={scheduled.run.run_id}" in caplog.text
    assert "detect started trigger=manual" in caplog.text
    assert f"detect finished trigger=manual run_id={manual.run.run_id}" in caplog.text


def _one(findings):
    matches = [finding for finding in findings if finding.finding_id == _FINDING]
    assert len(matches) == 1
    return matches[0]


def test_unknown_trigger_is_rejected(session: Session) -> None:
    with pytest.raises(ValueError, match="unknown detection trigger"):
        run_once(session, "queue")
