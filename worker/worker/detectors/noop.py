"""Detector that always emits nothing."""

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.schemas import Resource


class NoOpDetector:
    name = "noop"

    def detect(self, resources: list[Resource], session: Session | None = None) -> list[Finding]:
        return []
