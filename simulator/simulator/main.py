import uvicorn
from fastapi import FastAPI

from simulator.mutate_api import mount_mutations
from simulator.read_api import mount_read_api
from simulator.world import World


def create_app() -> FastAPI:
    world = World()
    app = FastAPI(
        title="CloudSentry Simulator",
        version="0.1.0",
        description=(
            "Seeded AWS-like company. Reads return current state. "
            "Actions can be rolled back. This API does not call AWS."
        ),
    )

    @app.get("/health", tags=["system"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    mount_read_api(app, world)
    mount_mutations(app, world)
    return app


app = create_app()


def run() -> None:
    uvicorn.run("simulator.main:app", host="127.0.0.1", port=8001, reload=True)
