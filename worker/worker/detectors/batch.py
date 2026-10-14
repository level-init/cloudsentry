"""Run every registered detector and upsert the findings."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db import create_session
from app.proposals import Finding
from app.repositories import FindingRepository, ResourceRepository
from worker.detectors.registry import DetectorRegistry, default_registry


@dataclass(frozen=True)
class DetectResult:
    detectors: int
    created: int
    updated: int
    findings: list[Finding]


def detect(registry: DetectorRegistry | None = None) -> DetectResult:
    session = create_session()
    try:
        result = run_batch(session, registry)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return result


def run_batch(session: Session, registry: DetectorRegistry | None = None) -> DetectResult:
    chosen = default_registry() if registry is None else registry
    resources = [resource for resource in ResourceRepository(session).list() if resource.present]
    findings: list[Finding] = []
    for detector in chosen.detectors():
        findings.extend(detector.detect(resources))
    repository = FindingRepository(session)
    created = 0
    for finding in findings:
        if repository.upsert(finding):
            created += 1
    return DetectResult(
        detectors=len(chosen.detectors()),
        created=created,
        updated=len(findings) - created,
        findings=findings,
    )
