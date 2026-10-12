"""Mutation HTTP API for the simulator world.

Each action records the prior field. Rollback writes that field back.
"""

from collections.abc import Callable

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from simulator.model import SimResource
from simulator.world import Mutation, World


class ResizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule: str = Field(min_length=1)


class LifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_class: str = Field(min_length=1)


class MutationResponse(BaseModel):
    action_id: str
    action: str
    resource_id: str
    resource: SimResource | None


def mount_mutations(app: FastAPI, world: World) -> None:
    app.include_router(_routes(world))


def _routes(world: World) -> APIRouter:
    api = APIRouter()

    @api.post("/resources/{resource_id}/actions/stop", tags=["actions"], summary="Stop compute")
    def stop(resource_id: str) -> MutationResponse:
        return _apply(world, world.stop, resource_id)

    @api.post("/resources/{resource_id}/actions/start", tags=["actions"], summary="Start compute")
    def start(resource_id: str) -> MutationResponse:
        return _apply(world, world.start, resource_id)

    @api.post("/resources/{resource_id}/actions/resize", tags=["actions"], summary="Resize compute")
    def resize(resource_id: str, body: ResizeRequest) -> MutationResponse:
        return _apply(world, lambda resource: world.resize(resource, body.sku), resource_id)

    @api.post(
        "/resources/{resource_id}/actions/schedule",
        tags=["actions"],
        summary="Set a development compute schedule",
    )
    def schedule(resource_id: str, body: ScheduleRequest) -> MutationResponse:
        return _apply(world, lambda resource: world.schedule(resource, body.schedule), resource_id)

    @api.post(
        "/resources/{resource_id}/actions/delete-unattached",
        tags=["actions"],
        summary="Delete an unattached disk",
    )
    def delete_unattached(resource_id: str) -> MutationResponse:
        return _apply(world, world.delete_unattached, resource_id)

    @api.post(
        "/resources/{resource_id}/actions/storage-lifecycle",
        tags=["actions"],
        summary="Change object storage class",
    )
    def storage_lifecycle(resource_id: str, body: LifecycleRequest) -> MutationResponse:
        return _apply(
            world,
            lambda resource: world.storage_lifecycle(resource, body.storage_class),
            resource_id,
        )

    @api.post("/actions/{action_id}/rollback", tags=["actions"], summary="Roll back one action")
    def rollback(action_id: str) -> MutationResponse:
        try:
            resource = world.rollback(action_id)
        except ValueError as exc:
            raise _error(exc) from exc
        return MutationResponse(
            action_id=action_id,
            action="rollback",
            resource_id=resource.resource_id,
            resource=resource,
        )

    return api


def _apply(world: World, action: Callable[[str], Mutation], resource_id: str) -> MutationResponse:
    try:
        mutation = action(resource_id)
    except ValueError as exc:
        raise _error(exc) from exc
    resource = None
    if mutation.action != "delete_unattached":
        resource = _find(world, mutation.resource_id)
    return MutationResponse(
        action_id=mutation.action_id,
        action=mutation.action,
        resource_id=mutation.resource_id,
        resource=resource,
    )


def _find(world: World, resource_id: str) -> SimResource | None:
    return next(
        (item for item in world.inventory.resources if item.resource_id == resource_id),
        None,
    )


def _error(exc: ValueError) -> HTTPException:
    message = str(exc)
    missing = message.startswith("unknown resource") or message.startswith("unknown action")
    status = 404 if missing else 400
    return HTTPException(status_code=status, detail=message)
