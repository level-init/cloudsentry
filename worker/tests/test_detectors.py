from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import sqlalchemy_database_url
from app.repositories import FindingRepository, ResourceRepository
from app.schemas import Resource
from worker.detectors import NoOpDetector, SampleDetector, run_batch
from worker.detectors.registry import DetectorRegistry


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


def test_sample_detector_skips_untagged_and_absent_resources() -> None:
    findings = SampleDetector().detect(
        [
            _resource("i-detect-sample", {"scenario": "sample"}),
            _resource("i-detect-other", {"scenario": "idle_compute"}),
            _resource("i-detect-absent", {"scenario": "sample"}, present=False),
        ]
    )

    assert [finding.resource_ids for finding in findings] == [["i-detect-sample"]]
    assert findings[0].evidence == ["tag scenario=sample on i-detect-sample"]
    assert NoOpDetector().detect([]) == []


def test_batch_runs_sample_and_noop_and_keeps_the_finding(session: Session) -> None:
    resources = ResourceRepository(session)
    resources.create(_resource("i-detect-sample", {"scenario": "sample"}))
    resources.create(_resource("i-detect-other", {"scenario": "idle_compute"}))

    first = run_batch(session)
    sample = _one(first.findings, "sample-i-detect-sample")
    stored = FindingRepository(session).get("sample-i-detect-sample")

    assert first.detectors == 6
    assert sample.resource_ids == ["i-detect-sample"]
    assert sample.category == "sample"
    assert sample.evidence == ["tag scenario=sample on i-detect-sample"]
    assert stored == sample
    assert all("i-detect-other" not in finding.resource_ids for finding in first.findings)

    second = run_batch(session)
    assert _one(second.findings, "sample-i-detect-sample") == sample
    assert second.created == 0
    assert second.updated == len(second.findings)
    assert FindingRepository(session).get("sample-i-detect-sample") == sample


def test_registry_rejects_a_duplicate_name() -> None:
    registry = DetectorRegistry()
    registry.register(SampleDetector())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(SampleDetector())


def _one(findings, finding_id: str):
    matches = [finding for finding in findings if finding.finding_id == finding_id]
    assert len(matches) == 1
    return matches[0]


def _resource(resource_id: str, tags: dict[str, str], present: bool = True) -> Resource:
    return Resource(
        resource_id=resource_id,
        resource_type="compute",
        account_id="111111111111",
        environment="development",
        owner="payments",
        team="payments",
        business_criticality="low",
        tags=tags,
        present=present,
    )
