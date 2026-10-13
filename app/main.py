"""FastAPI application entry point: `uvicorn app.main:app`."""

from fastapi import APIRouter, Depends, FastAPI

from app.access.sessions import require_workspace
from app.log import configure_logging
from app.web import access, health
from app.web.errors import add_error_handlers


def create_app() -> FastAPI:
    configure_logging()
    # The interactive docs and the OpenAPI schema are switched off: nothing but
    # the code entry endpoint and the health check is reachable without a session.
    app = FastAPI(title="RecruitDesk", docs_url=None, redoc_url=None, openapi_url=None)
    add_error_handlers(app)

    # Public routes. Keep this list short (PRD F0, CLAUDE.md rule 14).
    app.include_router(health.router)
    app.include_router(access.public_router)

    # Everything else goes under this router, which requires a valid session.
    protected = APIRouter(prefix="/api", dependencies=[Depends(require_workspace)])
    protected.include_router(access.router)
    app.include_router(protected)

    return app


app = create_app()
