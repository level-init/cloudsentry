"""Built-in detectors. Importing this package registers them."""

from worker.detectors.batch import DetectResult, detect, run_batch
from worker.detectors.idle import IdleComputeDetector
from worker.detectors.noop import NoOpDetector
from worker.detectors.registry import Detector, DetectorRegistry, default_registry
from worker.detectors.rightsizing import RightsizingDetector
from worker.detectors.sample import SampleDetector

default_registry().register(NoOpDetector())
default_registry().register(SampleDetector())
default_registry().register(IdleComputeDetector())
default_registry().register(RightsizingDetector())

__all__ = [
    "DetectResult",
    "Detector",
    "DetectorRegistry",
    "IdleComputeDetector",
    "NoOpDetector",
    "RightsizingDetector",
    "SampleDetector",
    "default_registry",
    "detect",
    "run_batch",
]
