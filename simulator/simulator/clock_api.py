"""HTTP controls for the simulator clock."""

from datetime import datetime

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from simulator.world import World


class ClockView(BaseModel):
    now: datetime


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=3660)


class SetClockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: datetime


def mount_clock(app: FastAPI, world: World) -> None:
    app.include_router(_routes(world))


def _routes(world: World) -> APIRouter:
    api = APIRouter()

    @api.get("/clock", tags=["clock"], summary="Read the simulator clock")
    def get_clock() -> ClockView:
        return ClockView(now=world.now)

    @api.put("/clock", tags=["clock"], summary="Set the simulator clock")
    def set_clock(body: SetClockRequest) -> ClockView:
        try:
            world.set_clock(body.now)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ClockView(now=world.now)

    @api.post("/clock/advance", tags=["clock"], summary="Advance the simulator clock")
    def advance(body: AdvanceRequest) -> ClockView:
        world.advance_days(body.days)
        return ClockView(now=world.now)

    return api
