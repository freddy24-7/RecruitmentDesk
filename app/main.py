"""FastAPI application entry point: `uvicorn app.main:app`."""

from fastapi import FastAPI

from app.web import health


def create_app() -> FastAPI:
    app = FastAPI(title="RecruitDesk")
    app.include_router(health.router)
    return app


app = create_app()
