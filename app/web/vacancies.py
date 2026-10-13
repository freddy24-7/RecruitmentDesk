"""Vacancies and their jobs. Every query is limited to the caller's workspace."""

import uuid
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.sessions import CurrentWorkspace
from app.config import Settings, get_settings
from app.db import get_session
from app.jobs.messages import message_for
from app.jobs.models import Job
from app.jobs.runner import JobRunner
from app.limits.workspace import LimitReached
from app.vacancy import review, service
from app.vacancy.deletion import ConfirmationRequired, delete_vacancy
from app.vacancy.models import DRAFT, FAILED, Vacancy
from app.vacancy.schemas import (
    COMPANY_MAX,
    EMPHASIS_MAX,
    TITLE_MAX,
    DraftSections,
    Sector,
    Seniority,
    VacancyParameters,
    WorkMode,
)
from app.web.errors import ApiError

log = structlog.get_logger()

router = APIRouter()

Db = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


def get_runner(request: Request) -> JobRunner:
    runner: JobRunner = request.app.state.job_runner
    return runner


Runner = Annotated[JobRunner, Depends(get_runner)]


class JobOut(BaseModel):
    id: uuid.UUID
    type: str
    status: str
    progress_done: int
    progress_total: int
    error_kind: str | None
    # What to show the user when the job failed or was interrupted.
    message: str | None
    vacancy_id: uuid.UUID | None


class ActionOut(BaseModel):
    key: str
    label: str
    enabled: bool
    reason: str | None


class VacancyOut(BaseModel):
    id: uuid.UUID
    status: str
    parameters: dict[str, Any]
    sections: dict[str, Any] | None
    flags: list[dict[str, str]]
    version: int
    # True when the text differs from what the model wrote.
    edited: bool
    created_at: datetime
    submitted_at: datetime | None
    # What can be done with a submitted vacancy, with the reason when it cannot.
    actions: list[ActionOut]
    # The most recent job for this vacancy.
    job: JobOut | None


class StartedOut(BaseModel):
    vacancy_id: uuid.UUID
    job_id: uuid.UUID


class OptionsOut(BaseModel):
    sectors: list[str]
    seniorities: list[str]
    work_modes: list[str]
    title_max: int
    company_max: int
    emphasis_max: int


def _job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        type=job.type,
        status=job.status,
        progress_done=job.progress_done,
        progress_total=job.progress_total,
        error_kind=job.error_kind,
        message=message_for(job.error_kind),
        vacancy_id=job.vacancy_id,
    )


async def _vacancy_out(session: AsyncSession, vacancy: Vacancy) -> VacancyOut:
    job = await session.scalar(
        select(Job)
        .where(Job.vacancy_id == vacancy.id)
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return VacancyOut(
        id=vacancy.id,
        status=vacancy.status,
        parameters=vacancy.parameters,
        sections=vacancy.sections,
        flags=vacancy.flags,
        version=vacancy.version,
        edited=vacancy.sections != vacancy.generated_sections,
        created_at=vacancy.created_at,
        submitted_at=vacancy.submitted_at,
        actions=[
            ActionOut(
                key=action.key,
                label=action.label,
                enabled=action.enabled,
                reason=action.reason,
            )
            for action in review.available_actions(vacancy)
        ],
        job=_job_out(job) if job else None,
    )


def _limit_error(limit: LimitReached) -> ApiError:
    return ApiError(409, limit.kind, limit.message)


@router.get("/vacancy-options")
async def read_options() -> OptionsOut:
    """The choices for the dialog, so the lists live in one place."""
    return OptionsOut(
        sectors=[sector.value for sector in Sector],
        seniorities=[level.value for level in Seniority],
        work_modes=[mode.value for mode in WorkMode],
        title_max=TITLE_MAX,
        company_max=COMPANY_MAX,
        emphasis_max=EMPHASIS_MAX,
    )


@router.post("/vacancies", status_code=202)
async def generate_vacancy(
    parameters: VacancyParameters,
    workspace: CurrentWorkspace,
    session: Db,
    settings: Config,
    runner: Runner,
) -> StartedOut:
    """Start generating a vacancy in the background and return at once."""
    try:
        vacancy, job = await service.start_generation(
            session, workspace.id, parameters, settings
        )
    except LimitReached as limit:
        raise _limit_error(limit) from limit
    await session.commit()
    runner.start(job.id)
    log.info("vacancy.generation_started", vacancy_id=str(vacancy.id))
    return StartedOut(vacancy_id=vacancy.id, job_id=job.id)


@router.get("/vacancies")
async def list_vacancies(workspace: CurrentWorkspace, session: Db) -> list[VacancyOut]:
    vacancies = await session.scalars(
        select(Vacancy)
        .where(Vacancy.workspace_id == workspace.id)
        .order_by(Vacancy.created_at.desc())
    )
    return [await _vacancy_out(session, vacancy) for vacancy in vacancies.all()]


async def _own_vacancy(
    session: AsyncSession, vacancy_id: uuid.UUID, workspace_id: uuid.UUID
) -> Vacancy:
    vacancy = await session.scalar(
        select(Vacancy).where(
            Vacancy.id == vacancy_id, Vacancy.workspace_id == workspace_id
        )
    )
    if vacancy is None:
        raise ApiError(404, "not_found", "This vacancy does not exist.")
    return vacancy


@router.get("/vacancies/{vacancy_id}")
async def read_vacancy(
    vacancy_id: uuid.UUID, workspace: CurrentWorkspace, session: Db
) -> VacancyOut:
    return await _vacancy_out(
        session, await _own_vacancy(session, vacancy_id, workspace.id)
    )


@router.put("/vacancies/{vacancy_id}/sections")
async def edit_vacancy(
    vacancy_id: uuid.UUID,
    sections: DraftSections,
    workspace: CurrentWorkspace,
    session: Db,
) -> VacancyOut:
    """Save edited sections as a new version (PRD F2)."""
    vacancy = await _own_vacancy(session, vacancy_id, workspace.id)
    try:
        changed = review.save_edits(vacancy, sections)
    except review.NotAllowed as refused:
        raise ApiError(409, refused.kind, refused.message) from refused
    except review.SectionsIncomplete as incomplete:
        raise ApiError(422, "sections_incomplete", incomplete.message) from incomplete
    await session.commit()
    if changed:
        log.info("vacancy.edited", vacancy_id=str(vacancy.id), version=vacancy.version)
    return await _vacancy_out(session, vacancy)


@router.post("/vacancies/{vacancy_id}/reset")
async def reset_vacancy(
    vacancy_id: uuid.UUID, workspace: CurrentWorkspace, session: Db
) -> VacancyOut:
    """Go back to the text as the model wrote it. Edits are lost."""
    vacancy = await _own_vacancy(session, vacancy_id, workspace.id)
    try:
        review.reset_to_generated(vacancy)
    except review.NotAllowed as refused:
        raise ApiError(409, refused.kind, refused.message) from refused
    await session.commit()
    log.info("vacancy.reset", vacancy_id=str(vacancy.id), version=vacancy.version)
    return await _vacancy_out(session, vacancy)


@router.post("/vacancies/{vacancy_id}/submit")
async def submit_vacancy(
    vacancy_id: uuid.UUID, workspace: CurrentWorkspace, session: Db
) -> VacancyOut:
    vacancy = await _own_vacancy(session, vacancy_id, workspace.id)
    try:
        review.submit(vacancy)
    except review.NotAllowed as refused:
        raise ApiError(409, refused.kind, refused.message) from refused
    except review.SectionsIncomplete as incomplete:
        raise ApiError(422, "sections_incomplete", incomplete.message) from incomplete
    await session.commit()
    log.info("vacancy.submitted", vacancy_id=str(vacancy.id))
    return await _vacancy_out(session, vacancy)


@router.delete("/vacancies/{vacancy_id}", status_code=204)
async def cancel_vacancy(
    vacancy_id: uuid.UUID,
    workspace: CurrentWorkspace,
    session: Db,
    confirm: bool = False,
) -> Response:
    """Cancel vacancy: delete the draft and all related data (PRD F2).

    Destructive, so the caller must send `confirm=true`. The UI does that
    only after its confirmation dialog.
    """
    vacancy = await _own_vacancy(session, vacancy_id, workspace.id)
    if vacancy.status not in (DRAFT, FAILED):
        raise ApiError(
            409,
            "not_cancellable",
            "Only a draft can be cancelled, and not while it is being written.",
        )
    try:
        await delete_vacancy(session, vacancy, confirmed=confirm)
    except ConfirmationRequired as missing:
        raise ApiError(
            400,
            "confirmation_required",
            "Deleting a vacancy needs an explicit confirmation.",
        ) from missing
    await session.commit()
    log.info("vacancy.cancelled", vacancy_id=str(vacancy_id))
    return Response(status_code=204)


async def _own_job(
    session: AsyncSession, job_id: uuid.UUID, workspace_id: uuid.UUID
) -> Job:
    job = await session.scalar(
        select(Job).where(Job.id == job_id, Job.workspace_id == workspace_id)
    )
    if job is None:
        raise ApiError(404, "not_found", "This job does not exist.")
    return job


@router.get("/jobs/{job_id}")
async def read_job(
    job_id: uuid.UUID, workspace: CurrentWorkspace, session: Db
) -> JobOut:
    return _job_out(await _own_job(session, job_id, workspace.id))


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(
    job_id: uuid.UUID,
    workspace: CurrentWorkspace,
    session: Db,
    settings: Config,
    runner: Runner,
) -> JobOut:
    """Run a failed or interrupted job again."""
    job = await _own_job(session, job_id, workspace.id)
    try:
        queued = await service.retry_generation(session, job, settings)
    except LimitReached as limit:
        raise _limit_error(limit) from limit
    if not queued:
        raise ApiError(409, "not_retryable", "This job cannot be run again.")
    await session.commit()
    await session.refresh(job)
    runner.start(job.id)
    return _job_out(job)
