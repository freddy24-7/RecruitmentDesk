"""FastAPI application entry point: `uvicorn app.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, Depends, FastAPI

from app.access.sessions import require_workspace
from app.config import get_settings
from app.db import get_sessionmaker
from app.jobs.runner import JobRunner, mark_interrupted_jobs
from app.limits.workspace import VACANCY_GENERATION
from app.llm.base import LlmClient
from app.llm.pricing import require_known_price
from app.llm.service import LlmService, build_client
from app.log import configure_logging
from app.vacancy.service import VacancyGenerator, fail_generating_vacancies
from app.web import access, health, vacancies
from app.web.errors import add_error_handlers

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Jobs run inside this process. Whatever was running before a restart is
    # gone: mark it, so the user sees it and can run it again.
    async with get_sessionmaker()() as session:
        interrupted = await mark_interrupted_jobs(session)
        await fail_generating_vacancies(session)
        await session.commit()
    if interrupted:
        log.warning("jobs.interrupted_by_restart", count=interrupted)
    yield
    runner: JobRunner = app.state.job_runner
    await runner.shutdown()


def create_app(llm_client: LlmClient | None = None) -> FastAPI:
    """Build the application. Tests pass a fake `llm_client`."""
    configure_logging()
    settings = get_settings()
    require_known_price(settings.mistral_model_vacancy)

    # The interactive docs and the OpenAPI schema are switched off: nothing but
    # the code entry endpoint and the health check is reachable without a session.
    app = FastAPI(
        title="RecruitDesk",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    add_error_handlers(app)

    sessionmaker = get_sessionmaker()
    llm = LlmService(llm_client or build_client(settings), sessionmaker)
    app.state.llm = llm
    app.state.job_runner = JobRunner(
        sessionmaker,
        handlers={VACANCY_GENERATION: VacancyGenerator(llm, settings)},
    )

    # Public routes. Keep this list short (PRD F0, CLAUDE.md rule 14).
    app.include_router(health.router)
    app.include_router(access.public_router)

    # Everything else goes under this router, which requires a valid session.
    protected = APIRouter(prefix="/api", dependencies=[Depends(require_workspace)])
    protected.include_router(access.router)
    protected.include_router(vacancies.router)
    app.include_router(protected)

    return app


app = create_app()
