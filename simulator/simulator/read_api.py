"""HTTP reads for the simulator world.

Callers page through inventory and ask for metrics, costs, tags,
dependencies, and incidents per resource.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel

from simulator.billing import CostLine, daily_costs
from simulator.clock import last_observed_day
from simulator.incidents import Incident, incidents_for
from simulator.metrics import history_start, query_metrics
from simulator.model import Inventory, SimResource
from simulator.world import World

router = APIRouter()


class ResourcePage(BaseModel):
    items: list[SimResource]
    total: int
    limit: int
    offset: int


class CostReport(BaseModel):
    resource_id: str
    year: int
    month: int
    total_cents: int
    lines: list[CostLine]


def mount_read_api(app: FastAPI, world: World) -> None:
    app.state.world = world
    app.include_router(_routes(world))


def _routes(world: World) -> APIRouter:
    api = APIRouter()

    @api.get("/resources", tags=["inventory"], summary="List seeded resources")
    def list_resources(
        environment: str | None = None,
        account_id: str | None = None,
        resource_type: str | None = None,
        scenario: str | None = None,
        limit: int = Query(default=200, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> ResourcePage:
        inventory = world.inventory
        matched = [
            resource
            for resource in inventory.resources
            if _matches(resource, environment, account_id, resource_type, scenario)
        ]
        return ResourcePage(
            items=matched[offset : offset + limit],
            total=len(matched),
            limit=limit,
            offset=offset,
        )

    @api.get("/resources/{resource_id}", tags=["inventory"], summary="Fetch one resource")
    def get_resource(resource_id: str) -> SimResource:
        return _resource_or_404(world.inventory, resource_id)

    @api.get("/resources/{resource_id}/tags", tags=["inventory"], summary="Tags for one resource")
    def get_tags(resource_id: str) -> dict[str, str]:
        return _resource_or_404(world.inventory, resource_id).tags

    @api.get("/resources/{resource_id}/metrics", tags=["metrics"], summary="Hourly metrics")
    def get_metrics(
        resource_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        name: str | None = None,
    ) -> list:
        _resource_or_404(world.inventory, resource_id)
        window_start, window_end = _metric_window(start, end, world.now)
        try:
            return query_metrics(
                world.inventory,
                resource_id,
                start=window_start,
                end=window_end,
                name=name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.get("/resources/{resource_id}/costs", tags=["billing"], summary="Daily costs for a month")
    def get_costs(
        resource_id: str,
        year: int | None = None,
        month: int | None = None,
    ) -> CostReport:
        resource = _resource_or_404(world.inventory, resource_id)
        observed = last_observed_day(world.now)
        if year is None and month is None:
            year, month = observed.year, observed.month
        elif year is None or month is None or not 1 <= month <= 12:
            raise HTTPException(status_code=400, detail="year and month must be a real month")
        lines = [
            line
            for line in daily_costs(
                world.inventory,
                resource.account_id,
                year,
                month,
                through=observed,
            )
            if line.resource_id == resource_id
        ]
        return CostReport(
            resource_id=resource_id,
            year=year,
            month=month,
            total_cents=sum(line.amount_cents for line in lines),
            lines=lines,
        )

    @api.get(
        "/resources/{resource_id}/dependencies",
        tags=["dependencies"],
        summary="Resources this resource depends on",
    )
    def get_dependencies(resource_id: str) -> list:
        _resource_or_404(world.inventory, resource_id)
        return world.graph.dependencies(resource_id)

    @api.get(
        "/resources/{resource_id}/dependents",
        tags=["dependencies"],
        summary="Resources that depend on this resource",
    )
    def get_dependents(resource_id: str) -> list:
        _resource_or_404(world.inventory, resource_id)
        return world.graph.dependents(resource_id)

    @api.get(
        "/resources/{resource_id}/incidents",
        tags=["incidents"],
        summary="Incidents for one resource",
    )
    def get_incidents(resource_id: str) -> list[Incident]:
        _resource_or_404(world.inventory, resource_id)
        return incidents_for(world.inventory, world.incidents, resource_id)

    return api


def _matches(
    resource: SimResource,
    environment: str | None,
    account_id: str | None,
    resource_type: str | None,
    scenario: str | None,
) -> bool:
    if environment is not None and resource.environment != environment:
        return False
    if account_id is not None and resource.account_id != account_id:
        return False
    if resource_type is not None and resource.resource_type != resource_type:
        return False
    if scenario is not None and resource.tags.get("scenario") != scenario:
        return False
    return True


def _resource_or_404(inventory: Inventory, resource_id: str) -> SimResource:
    resource = next((item for item in inventory.resources if item.resource_id == resource_id), None)
    if resource is None:
        raise HTTPException(status_code=404, detail=f"unknown resource {resource_id}")
    return resource


def _metric_window(
    start: datetime | None,
    end: datetime | None,
    now: datetime,
) -> tuple[datetime, datetime]:
    if start is None and end is None:
        window_end = now
        window_start = max(history_start(), window_end - timedelta(days=1))
        return window_start, window_end
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="start and end must be set together")
    if start < history_start() or end > now:
        raise HTTPException(status_code=400, detail="metric window is outside the simulator clock")
    return start, end
