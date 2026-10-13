"""Candidates of a vacancy. Every query is limited to the caller's workspace."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.sessions import CurrentWorkspace
from app.candidates import service
from app.candidates.models import Candidate
from app.candidates.schemas import Cv
from app.candidates.timeline import total_years
from app.config import Settings, get_settings
from app.db import get_session
from app.limits.workspace import LimitReached
from app.vacancy.models import Vacancy
from app.web.errors import ApiError
from app.web.vacancies import JobOut, Runner, job_out, own_vacancy

log = structlog.get_logger()

router = APIRouter()

Db = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


class GenerateRequest(BaseModel):
    # The range (1 to 100) is checked in the service, which gives a clear message.
    count: int
    # Must be true when candidates already exist: they will be replaced.
    replace: bool = False


class CandidateSummary(BaseModel):
    """One row of the candidate page. It never includes the blueprint."""

    id: uuid.UUID
    number: int
    name: str
    email: str
    phone: str
    current_title: str
    current_company: str
    years_experience: float
    skills: list[str]


class CandidateList(BaseModel):
    vacancy_id: uuid.UUID
    vacancy_title: str
    # True when the vacancy was edited after these candidates were generated.
    out_of_date: bool
    candidates: list[CandidateSummary]


class CandidateDetail(CandidateSummary):
    out_of_date: bool
    cv: dict[str, Any]


def _summary(candidate: Candidate, cv: Cv) -> CandidateSummary:
    current = cv.positions[0]
    return CandidateSummary(
        id=candidate.id,
        number=candidate.number,
        name=candidate.name,
        email=candidate.email,
        phone=candidate.phone,
        current_title=current.title,
        current_company=current.company,
        # Computed from the dated jobs in the CV, as a recruiter would.
        years_experience=total_years(cv.positions, datetime.now(UTC).date()),
        skills=cv.skills,
    )


@router.post("/vacancies/{vacancy_id}/candidates", status_code=202)
async def generate_candidates(
    vacancy_id: uuid.UUID,
    body: GenerateRequest,
    workspace: CurrentWorkspace,
    session: Db,
    settings: Config,
    runner: Runner,
) -> JobOut:
    """Start generating candidates in the background and return at once."""
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    try:
        job = await service.start_generation(
            session, vacancy, body.count, body.replace, settings
        )
    except service.NotAllowed as refused:
        status = 422 if refused.kind == "invalid_count" else 409
        raise ApiError(status, refused.kind, refused.message) from refused
    except LimitReached as limit:
        raise ApiError(409, limit.kind, limit.message) from limit
    await session.commit()
    runner.start(job.id)
    log.info(
        "candidates.generation_started", vacancy_id=str(vacancy.id), count=body.count
    )
    return job_out(job)


async def _vacancy_title(vacancy: Vacancy) -> str:
    title = (vacancy.sections or {}).get("title") or vacancy.parameters.get("title")
    return str(title or "")


@router.get("/vacancies/{vacancy_id}/candidates")
async def list_candidates(
    vacancy_id: uuid.UUID, workspace: CurrentWorkspace, session: Db
) -> CandidateList:
    """Candidates whose CV is ready. Searching and sorting happen in the browser."""
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    candidates = (
        await session.scalars(
            select(Candidate)
            .where(Candidate.vacancy_id == vacancy.id, Candidate.cv.is_not(None))
            .order_by(Candidate.number)
        )
    ).all()
    return CandidateList(
        vacancy_id=vacancy.id,
        vacancy_title=await _vacancy_title(vacancy),
        out_of_date=any(c.vacancy_version != vacancy.version for c in candidates),
        candidates=[_summary(c, Cv.model_validate(c.cv)) for c in candidates],
    )


@router.get("/vacancies/{vacancy_id}/candidates/{candidate_id}")
async def read_candidate(
    vacancy_id: uuid.UUID,
    candidate_id: uuid.UUID,
    workspace: CurrentWorkspace,
    session: Db,
) -> CandidateDetail:
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    candidate = await session.scalar(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.vacancy_id == vacancy.id,
            Candidate.cv.is_not(None),
        )
    )
    if candidate is None:
        raise ApiError(404, "not_found", "This candidate does not exist.")
    cv = Cv.model_validate(candidate.cv)
    return CandidateDetail(
        **_summary(candidate, cv).model_dump(),
        out_of_date=candidate.vacancy_version != vacancy.version,
        cv=cv.model_dump(mode="json"),
    )
