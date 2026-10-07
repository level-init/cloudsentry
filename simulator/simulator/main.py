import uvicorn
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="CloudSentry Simulator")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


def run() -> None:
    uvicorn.run("simulator.main:app", host="127.0.0.1", port=8001, reload=True)
