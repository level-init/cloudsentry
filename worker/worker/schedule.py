"""Record one detection batch for a manual trigger or a cron tick.

`detect` is the manual path. `detect-schedule` is the scheduled path. Cron
should invoke the scheduled command every `DETECTION_INTERVAL_SECONDS`
(default 3600). Each invocation inserts one `detection_runs` row. Findings
are still upserted by `finding_id`, so a later tick updates those rows.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db import create_session
from app.repositories import DetectionRunRepository
from app.schemas import DetectionRun
from worker.config import get_settings
from worker.detectors.batch import DetectResult, run_batch
from worker.detectors.registry import DetectorRegistry

_TRIGGERS = frozenset({"manual", "schedule"})


@dataclass(frozen=True)
class RecordedDetect:
    run: DetectionRun
    result: DetectResult


def run_recorded(
    trigger: str,
    registry: DetectorRegistry | None = None,
    interval_seconds: int | None = None,
) -> DetectResult:
    session = create_session()
    try:
        recorded = run_once(session, trigger, registry, interval_seconds)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return recorded.result


def detect_scheduled(
    registry: DetectorRegistry | None = None,
    interval_seconds: int | None = None,
) -> DetectResult:
    return run_recorded("schedule", registry, interval_seconds)


def run_once(
    session: Session,
    trigger: str,
    registry: DetectorRegistry | None = None,
    interval_seconds: int | None = None,
) -> RecordedDetect:
    if trigger not in _TRIGGERS:
        raise ValueError(f"unknown detection trigger {trigger}")
    interval = (
        get_settings().detection_interval_seconds if interval_seconds is None else interval_seconds
    )
    if interval <= 0:
        raise ValueError("detection interval must be positive")
    started = datetime.now(UTC)
    logging.info("detect started trigger=%s interval_seconds=%s", trigger, interval)
    result = run_batch(session, registry)
    finished = datetime.now(UTC)
    run = DetectionRunRepository(session).create(
        trigger=trigger,
        interval_seconds=interval,
        started_at=started,
        finished_at=finished,
        detectors=result.detectors,
        created=result.created,
        updated=result.updated,
        findings=len(result.findings),
    )
    logging.info(
        "detect finished trigger=%s run_id=%s detectors=%s created=%s updated=%s findings=%s",
        trigger,
        run.run_id,
        run.detectors,
        run.created,
        run.updated,
        run.findings,
    )
    return RecordedDetect(run=run, result=result)
