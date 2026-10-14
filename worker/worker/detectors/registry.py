"""Detector interface and registry.

A detector reads the resources it is given and may read the session. It does
not write. The batch runner persists what the detectors return.
"""

from typing import Protocol

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.schemas import Resource


class Detector(Protocol):
    name: str

    def detect(self, resources: list[Resource], session: Session) -> list[Finding]:
        """Return findings for this pass. An empty list is a successful no-op."""


class DetectorRegistry:
    def __init__(self) -> None:
        self._detectors: dict[str, Detector] = {}

    def register(self, detector: Detector) -> None:
        if detector.name in self._detectors:
            raise ValueError(f"detector {detector.name} is already registered")
        self._detectors[detector.name] = detector

    def detectors(self) -> list[Detector]:
        return [self._detectors[name] for name in sorted(self._detectors)]


_registry = DetectorRegistry()


def default_registry() -> DetectorRegistry:
    return _registry
