"""Read-only HTTP API for the seeded company.

Mutations are intentionally absent. Callers page through inventory and ask
for metrics, costs, tags, dependencies, and incidents per resource.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel

from simulator.billing import CostLine, daily_costs
from simulator.dependencies import DependencyGraph, dependency_graph
from simulator.incidents import Incident, incidents_for, seed_incidents
from simulator.metrics import HISTORY_END, history_start, query_metrics
from simulator.model import Inventory, SimResource
from simulator.seed import seed_company

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


def mount_read_api(app: FastAPI) -> None:
    inventory = seed_company()
    graph = dependency_graph(inventory)
    incidents = seed_incidents(inventory)
    app.state.inventory = inventory
    app.include_router(_routes(inventory, graph, incidents))


def _routes(inventory: Inventory, graph: DependencyGraph, incidents: list[Incident]) -> APIRouter:
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
        return _resource_or_404(inventory, resource_id)

    @api.get("/resources/{resource_id}/tags", tags=["inventory"], summary="Tags for one resource")
    def get_tags(resource_id: str) -> dict[str, str]:
        return _resource_or_404(inventory, resource_id).tags

    @api.get("/resources/{resource_id}/metrics", tags=["metrics"], summary="Hourly metrics")
    def get_metrics(
        resource_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        name: str | None = None,
    ) -> list:
        _resource_or_404(inventory, resource_id)
        window_start, window_end = _metric_window(start, end)
        try:
            return query_metrics(
                inventory,
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
        year: int = 2026,
        month: int = Query(default=3, ge=1, le=12),
    ) -> CostReport:
        resource = _resource_or_404(inventory, resource_id)
        lines = [
            line
            for line in daily_costs(inventory, resource.account_id, year, month)
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
        _resource_or_404(inventory, resource_id)
        return graph.dependencies(resource_id)

    @api.get(
        "/resources/{resource_id}/dependents",
        tags=["dependencies"],
        summary="Resources that depend on this resource",
    )
    def get_dependents(resource_id: str) -> list:
        _resource_or_404(inventory, resource_id)
        return graph.dependents(resource_id)

    @api.get(
        "/resources/{resource_id}/incidents",
        tags=["incidents"],
        summary="Incidents for one resource",
    )
    def get_incidents(resource_id: str) -> list[Incident]:
        _resource_or_404(inventory, resource_id)
        return incidents_for(inventory, incidents, resource_id)

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


def _metric_window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    if start is None and end is None:
        window_start = history_start()
        return window_start, window_start + timedelta(days=1)
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="start and end must be set together")
    if end > HISTORY_END or start < history_start():
        raise HTTPException(status_code=400, detail="metric window is outside seeded history")
    return start, end
