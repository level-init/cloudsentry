import uvicorn
from fastapi import FastAPI

from app.config import get_settings


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(title="CloudSentry API")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


def run() -> None:
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)