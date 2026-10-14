"""Detector that always emits nothing."""

from app.proposals import Finding
from app.schemas import Resource


class NoOpDetector:
    name = "noop"

    def detect(self, resources: list[Resource]) -> list[Finding]:
        return []
