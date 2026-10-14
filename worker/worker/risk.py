"""Score how risky a change to one resource is.

The inputs are the stored resource, its dependency edges, its incidents, and
the CPU peak over the same 30-day window the detectors use. Points add up and
then cap at 1. The same inputs always return the same score.

Production, a high criticality, a CPU peak of at least 80, dependents, and
incidents raise the score. A development resource with low criticality, a low
peak, and no incidents stays near 0. That is why i-prd-017 scores above
i-dev-062, and a production resource with a dependent and an incident scores
higher still.

The class stays APPROVAL_REQUIRED. Mapping a score onto SAFE_AUTOMATION,
ENGINEERING_REVIEW_REQUIRED, or REJECTED is a later step. v1 still waits for
a person to approve before anything runs.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from app.proposals import RiskAssessment, RiskClass
from app.repositories import (
    DependencyRepository,
    IncidentRepository,
    MetricRollupRepository,
    ResourceRepository,
)
from worker.detectors.idle import WINDOW_DAYS

_ENVIRONMENT = {"development": 0.0, "staging": 0.1, "production": 0.25}
_CRITICALITY = {"low": 0.0, "medium": 0.1, "high": 0.2}
_INCIDENT = {"low": 0.05, "medium": 0.1, "high": 0.2}
_DEPENDENCY = 0.05
_DEPENDENT = 0.1
_DEPENDENT_CAP = 0.2
_INCIDENT_CAP = 0.2


@dataclass(frozen=True)
class RiskInputs:
    environment: str
    criticality: str
    cpu_peak: float | None
    dependency_count: int
    dependent_count: int
    incident_severities: tuple[str, ...]


def assess(session: Session, resource_id: str) -> RiskAssessment:
    resource = ResourceRepository(session).get(resource_id)
    if resource is None:
        raise ValueError(f"unknown resource {resource_id}")
    dependencies = DependencyRepository(session)
    incidents = IncidentRepository(session).for_resource(resource_id)
    return score_risk(
        RiskInputs(
            environment=_text(resource.environment),
            criticality=_text(resource.business_criticality),
            cpu_peak=_cpu_peak(session, resource_id),
            dependency_count=len(dependencies.dependencies_of(resource_id)),
            dependent_count=len(dependencies.dependents_of(resource_id)),
            incident_severities=tuple(_text(incident.severity) for incident in incidents),
        )
    )


def score_risk(inputs: RiskInputs) -> RiskAssessment:
    environment = _ENVIRONMENT.get(inputs.environment, 0.25)
    criticality = _CRITICALITY.get(inputs.criticality, 0.2)
    peak = _peak_points(inputs.cpu_peak)
    dependents = min(_DEPENDENT_CAP, _DEPENDENT * inputs.dependent_count)
    incident_points = min(
        _INCIDENT_CAP,
        sum(_INCIDENT.get(severity, 0.0) for severity in inputs.incident_severities),
    )
    dependencies = _DEPENDENCY if inputs.dependency_count else 0.0
    total = environment + criticality + peak + dependents + incident_points + dependencies
    return RiskAssessment(
        risk_score=round(min(total, 1.0), 2),
        risk_class=RiskClass.approval_required,
        reasons=_reasons(inputs),
    )


def _cpu_peak(session: Session, resource_id: str) -> float | None:
    rollups = MetricRollupRepository(session)
    latest = rollups.latest_day("cpu_percent")
    if latest is None:
        return None
    end = latest + timedelta(days=1)
    start = end - timedelta(days=WINDOW_DAYS)
    stats = rollups.window_summary([resource_id], "cpu_percent", start, end).get(resource_id)
    if stats is None:
        return None
    return stats[1]


def _peak_points(peak: float | None) -> float:
    if peak is None:
        return 0.0
    if peak >= 80:
        return 0.25
    if peak >= 50:
        return 0.15
    if peak >= 25:
        return 0.05
    return 0.0


def _reasons(inputs: RiskInputs) -> list[str]:
    if inputs.cpu_peak is None:
        peak = "CPU peak was not ingested"
    else:
        peak = f"CPU peak is {inputs.cpu_peak:.2f}"
    if inputs.dependent_count == 0:
        dependents = "Nothing depends on it"
    elif inputs.dependent_count == 1:
        dependents = "1 resource depends on it"
    else:
        dependents = f"{inputs.dependent_count} resources depend on it"
    if inputs.dependency_count == 0:
        dependencies = "It depends on no other resources"
    elif inputs.dependency_count == 1:
        dependencies = "It depends on 1 resource"
    else:
        dependencies = f"It depends on {inputs.dependency_count} resources"
    if not inputs.incident_severities:
        incidents = "No incidents are recorded"
    else:
        highest = max(inputs.incident_severities, key=lambda item: _INCIDENT.get(item, 0.0))
        count = len(inputs.incident_severities)
        label = "incident is" if count == 1 else "incidents are"
        incidents = f"{count} {label} recorded, highest severity {highest}"
    return [
        f"Environment is {inputs.environment}",
        f"Criticality is {inputs.criticality}",
        peak,
        dependents,
        dependencies,
        incidents,
    ]


def _text(value: object) -> str:
    return getattr(value, "value", value)
