import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings
from app.dependency_api import router as dependency_router
from app.notification_api import router as notification_router
from app.proposal_api import router as proposal_router
from app.resource_api import router as resource_router
from app.spend_api import router as spend_router

OPENAPI_TAGS = [
    {"name": "system", "description": "Process health."},
    {
        "name": "inventory",
        "description": "Resources, metrics, cost, dependencies, incidents, and policies.",
    },
    {
        "name": "proposals",
        "description": "Optimization proposals, risk, approval, execution, and verification.",
    },
    {
        "name": "notifications",
        "description": "In-app notices for proposals waiting on approval.",
    },
]


class HealthStatus(BaseModel):
    status: str


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(
        title="CloudSentry API",
        version="0.1.0",
        description=(
            "Closed-loop FinOps API. v1 is approval-required: a human approves "
            "a proposal before any change runs."
        ),
        openapi_tags=OPENAPI_TAGS,
    )
    app.include_router(resource_router)
    app.include_router(dependency_router)
    app.include_router(spend_router)
    app.include_router(proposal_router)
    app.include_router(notification_router)

    @app.get(
        "/health",
        tags=["system"],
        summary="Liveness check",
        description="Returns ok when the API process is running.",
        response_model=HealthStatus,
    )
    def health() -> HealthStatus:
        return HealthStatus(status="ok")

    return app


app = create_app()


def run() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
