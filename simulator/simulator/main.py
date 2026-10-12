import uvicorn
from fastapi import FastAPI

from simulator.read_api import mount_read_api


def create_app() -> FastAPI:
    app = FastAPI(
        title="CloudSentry Simulator",
        version="0.1.0",
        description=(
            "Read-only view of the seeded AWS-like company. This API does not mutate resources."
        ),
    )

    @app.get("/health", tags=["system"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    mount_read_api(app)
    return app


app = create_app()


def run() -> None:
    uvicorn.run("simulator.main:app", host="127.0.0.1", port=8001, reload=True)
