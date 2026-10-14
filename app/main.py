"""FastAPI application entry point: `uvicorn app.main:app`."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.access.sessions import require_workspace
from app.candidates.service import CandidateGenerator
from app.config import get_settings
from app.db import get_sessionmaker
from app.interview.service import InterviewQuestioner
from app.jobs.runner import JobRunner, mark_interrupted_jobs
from app.limits.workspace import (
    CANDIDATE_GENERATION,
    INTERVIEW_QUESTIONS,
    SCREENING,
    SCRIPT_PROPOSAL,
    VACANCY_GENERATION,
)
from app.llm.base import LlmClient
from app.llm.pricing import require_known_price
from app.llm.service import LlmService, build_client
from app.log import configure_logging
from app.screening.service import Screener
from app.script.service import ScriptProposer
from app.vacancy.deletion import delete_idle_workspaces
from app.vacancy.service import VacancyGenerator, fail_generating_vacancies
from app.web import (
    access,
    candidates,
    health,
    interview,
    screening,
    script,
    vacancies,
    workspace,
)
from app.web.errors import add_body_limit, add_error_handlers

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
    cleanup = asyncio.create_task(_clean_up_regularly())
    yield
    cleanup.cancel()
    runner: JobRunner = app.state.job_runner
    await runner.shutdown()


async def clean_up_once() -> int:
    """Delete idle workspaces and old failed attempts; return how many workspaces."""
    settings = get_settings()
    async with get_sessionmaker()() as session:
        deleted = await delete_idle_workspaces(
            session, datetime.now(UTC), timedelta(hours=settings.session_idle_hours)
        )
        await session.commit()
    if deleted:
        log.info("workspaces.cleaned_up", deleted=deleted)
    return deleted


async def _clean_up_regularly() -> None:
    """At startup, and then every so often, for as long as the app runs."""
    while True:
        try:
            await clean_up_once()
        except Exception as error:  # noqa: BLE001 - the loop must keep running
            log.error("workspaces.cleanup_failed", exception=type(error).__name__)
        await asyncio.sleep(get_settings().cleanup_interval_minutes * 60)


def create_app(llm_client: LlmClient | None = None) -> FastAPI:
    """Build the application. Tests pass a fake `llm_client`."""
    configure_logging()
    settings = get_settings()
    require_known_price(settings.mistral_model_vacancy)
    require_known_price(settings.mistral_model_profile)
    require_known_price(settings.mistral_model_cv)
    require_known_price(settings.mistral_model_script)
    require_known_price(settings.mistral_model_assessment)
    require_known_price(settings.mistral_model_interview)

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
    add_body_limit(app, settings.max_request_bytes)

    sessionmaker = get_sessionmaker()
    llm = LlmService(
        llm_client or build_client(settings),
        sessionmaker,
        daily_spend_cap=settings.daily_spend_cap_usd,
    )
    app.state.llm = llm
    app.state.job_runner = JobRunner(
        sessionmaker,
        handlers={
            VACANCY_GENERATION: VacancyGenerator(llm, settings),
            CANDIDATE_GENERATION: CandidateGenerator(llm, settings, sessionmaker),
            SCRIPT_PROPOSAL: ScriptProposer(llm, settings),
            SCREENING: Screener(llm, settings, sessionmaker),
            INTERVIEW_QUESTIONS: InterviewQuestioner(llm, settings, sessionmaker),
        },
    )

    # Public routes. Keep this list short (PRD F0, CLAUDE.md rule 14).
    app.include_router(health.router)
    app.include_router(access.public_router)

    # Everything else goes under this router, which requires a valid session.
    protected = APIRouter(prefix="/api", dependencies=[Depends(require_workspace)])
    protected.include_router(access.router)
    protected.include_router(vacancies.router)
    protected.include_router(candidates.router)
    protected.include_router(script.router)
    protected.include_router(screening.router)
    protected.include_router(interview.router)
    protected.include_router(workspace.router)
    app.include_router(protected)

    # Last, so it never shadows an API route. The page itself is public: it is
    # only the code entry screen until the API hands out a session.
    frontend = Path(settings.frontend_dist)
    if (frontend / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")

    return app


app = create_app()
