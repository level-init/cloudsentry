"""List and get resources with monthly cost and CPU utilization."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.repositories import CostRecordRepository, MetricRollupRepository, ResourceRepository
from app.schemas import Environment, Resource, ResourceList, ResourceSummary

router = APIRouter(prefix="/resources", tags=["inventory"])

_CPU = "cpu_percent"


@router.get(
    "",
    response_model=ResourceList,
    summary="List resources",
    description=(
        "Filters are account_id, environment, and resource_type. "
        "Each item includes monthly cost in cents and cpu_percent utilization "
        "for one calendar month. Omit year and month to use the latest month "
        "that has cost records. cpu_avg is the mean of daily averages and "
        "cpu_peak is the highest daily peak. A resource with no CPU series "
        "has null utilization."
    ),
)
def list_resources(
    account_id: str | None = None,
    environment: Environment | None = None,
    resource_type: str | None = None,
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    session: Session = Depends(get_session),
) -> ResourceList:
    chosen = _chosen_month(session, year, month)
    resources = ResourceRepository(session).list(
        environment=None if environment is None else environment.value,
        account_id=account_id,
        resource_type=resource_type,
    )
    items = _summaries(session, resources, chosen)
    return ResourceList(items=items, total=len(items))


@router.get(
    "/{resource_id}",
    response_model=ResourceSummary,
    summary="Get a resource",
    description="One resource with the same monthly cost and CPU summary as the list.",
)
def get_resource(
    resource_id: str,
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    session: Session = Depends(get_session),
) -> ResourceSummary:
    resource = ResourceRepository(session).get(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="resource not found")
    return _summaries(session, [resource], _chosen_month(session, year, month))[0]


def _chosen_month(
    session: Session,
    year: int | None,
    month: int | None,
) -> tuple[int, int] | None:
    if (year is None) != (month is None):
        raise HTTPException(status_code=422, detail="year and month are set together")
    if year is not None and month is not None:
        return year, month
    return CostRecordRepository(session).latest_month()


def _summaries(
    session: Session,
    resources: list[Resource],
    month: tuple[int, int] | None,
) -> list[ResourceSummary]:
    ids = [resource.resource_id for resource in resources]
    costs: dict[str, int] = {}
    cpu: dict[str, tuple[float, float]] = {}
    year = None if month is None else month[0]
    month_number = None if month is None else month[1]
    if month is not None:
        costs = CostRecordRepository(session).monthly_cents_by_resource(year, month_number, ids)
        start, end = _month_dates(year, month_number)
        cpu = MetricRollupRepository(session).utilization(ids, _CPU, start, end)
    return [
        ResourceSummary(
            **resource.model_dump(),
            monthly_cost_cents=costs.get(resource.resource_id, 0),
            cpu_avg=_rounded(cpu.get(resource.resource_id, (None, None))[0]),
            cpu_peak=_rounded(cpu.get(resource.resource_id, (None, None))[1]),
            year=year,
            month=month_number,
        )
        for resource in resources
    ]


def _month_dates(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month + 1, 1)


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)
