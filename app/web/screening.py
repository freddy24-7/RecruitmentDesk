"""The long list and short list of a vacancy. Limited to the caller's workspace.

Name, phone number and email address are joined back to the assessments
here, and only here: the scoring and assessment steps never see them
(CLAUDE.md rule 3).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.sessions import CurrentWorkspace
from app.candidates.models import Candidate
from app.config import Settings, get_settings
from app.db import get_session
from app.limits.workspace import LimitReached
from app.screening import service
from app.screening.models import Assessment
from app.script.models import SelectionScript
from app.web.errors import ApiError
from app.web.vacancies import JobOut, Runner, job_out, own_vacancy

log = structlog.get_logger()

router = APIRouter()

Db = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]

NOTICE = "Suggestions to support a recruiter. A person decides."


class ScreenRequest(BaseModel):
    # Must be true when lists already exist: they will be replaced.
    replace: bool = False


class FlagOut(BaseModel):
    kind: str
    detail: str


class EntryOut(BaseModel):
    """One candidate on a list (PRD F7)."""

    candidate_id: uuid.UUID
    position: int
    name: str
    phone: str
    email: str
    # The paragraph that explains why: keywords found, years, and what the
    # model found relevant.
    rationale: str
    strengths: list[str]
    concerns: list[str]
    flags: list[FlagOut]
    final_score: float
    deterministic_score: float
    llm_score: int
    on_short_list: bool


class RunOut(BaseModel):
    created_at: datetime
    candidates: int
    assessed: int
    long_size: int
    short_size: int
    weight_deterministic: float
    model: str


class ListsOut(BaseModel):
    notice: str
    vacancy_title: str
    out_of_date: bool
    run: RunOut
    long_list: list[EntryOut]
    short_list: list[EntryOut]


class RequirementOut(BaseModel):
    keywords: list[str]
    kind: str
    min_years: int
    met: bool
    keyword: str | None
    years: float


class SnippetOut(BaseModel):
    where: str
    text: str


class KeywordEvidenceOut(BaseModel):
    keyword: str
    years: float
    snippets: list[SnippetOut]


class EntryDetailOut(EntryOut):
    """An entry with its evidence: where in the CV each claim comes from."""

    notice: str
    total_years: float
    requirements: list[RequirementOut]
    evidence: list[KeywordEvidenceOut]


def _entry(row: Assessment, candidate: Candidate) -> EntryOut:
    return EntryOut(
        candidate_id=candidate.id,
        position=row.list_position or 0,
        name=candidate.name,
        phone=candidate.phone,
        email=candidate.email,
        rationale=row.rationale or "",
        strengths=row.strengths,
        concerns=row.concerns,
        flags=[FlagOut(**flag) for flag in row.flags],
        final_score=row.final_score or 0.0,
        deterministic_score=row.deterministic_score,
        llm_score=row.llm_score or 0,
        on_short_list=row.in_short_list,
    )


@router.post("/vacancies/{vacancy_id}/screening", status_code=202)
async def start_screening(
    vacancy_id: uuid.UUID,
    body: ScreenRequest,
    workspace: CurrentWorkspace,
    session: Db,
    settings: Config,
    runner: Runner,
) -> JobOut:
    """Start a screening run in the background: it produces both lists."""
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    try:
        job = await service.start_screening(session, vacancy, body.replace, settings)
    except service.NotAllowed as refused:
        raise ApiError(409, refused.kind, refused.message) from refused
    except LimitReached as limit:
        raise ApiError(409, limit.kind, limit.message) from limit
    await session.commit()
    runner.start(job.id)
    log.info("screening.started", vacancy_id=str(vacancy.id))
    return job_out(job)


async def _listed(
    session: AsyncSession, run_id: uuid.UUID
) -> list[tuple[Assessment, Candidate]]:
    rows = (
        await session.execute(
            select(Assessment, Candidate)
            .join(Candidate, Candidate.id == Assessment.candidate_id)
            .where(Assessment.run_id == run_id, Assessment.in_long_list.is_(True))
            .order_by(Assessment.list_position)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


@router.get("/vacancies/{vacancy_id}/lists")
async def read_lists(
    vacancy_id: uuid.UUID, workspace: CurrentWorkspace, session: Db
) -> ListsOut:
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    run = await service.latest_run(session, vacancy.id)
    if run is None:
        raise ApiError(404, "no_lists", "No lists have been generated yet.")
    script = await session.scalar(
        select(SelectionScript).where(SelectionScript.vacancy_id == vacancy.id)
    )
    entries = [
        _entry(row, candidate) for row, candidate in await _listed(session, run.job_id)
    ]
    result: dict[str, Any] = run.result
    return ListsOut(
        notice=NOTICE,
        vacancy_title=str((vacancy.sections or {}).get("title", "")),
        out_of_date=run.out_of_date(vacancy, script),
        run=RunOut(
            created_at=run.created_at,
            candidates=result["candidates"],
            assessed=result["assessed"],
            long_size=result["long_size"],
            short_size=result["short_size"],
            weight_deterministic=result["weight_deterministic"],
            model=result["model"],
        ),
        long_list=entries,
        short_list=[entry for entry in entries if entry.on_short_list],
    )


@router.get("/vacancies/{vacancy_id}/lists/{candidate_id}")
async def read_entry(
    vacancy_id: uuid.UUID,
    candidate_id: uuid.UUID,
    workspace: CurrentWorkspace,
    session: Db,
) -> EntryDetailOut:
    """One listed candidate with the evidence behind the assessment."""
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    run = await service.latest_run(session, vacancy.id)
    found = None
    if run is not None:
        found = (
            await session.execute(
                select(Assessment, Candidate)
                .join(Candidate, Candidate.id == Assessment.candidate_id)
                .where(
                    Assessment.run_id == run.job_id,
                    Assessment.candidate_id == candidate_id,
                    Assessment.in_long_list.is_(True),
                )
            )
        ).first()
    if found is None:
        raise ApiError(404, "not_found", "This candidate is not on a list.")
    row, candidate = found[0], found[1]
    script = await session.scalar(
        select(SelectionScript).where(SelectionScript.vacancy_id == vacancy.id)
    )
    items = script.items if script else []
    return EntryDetailOut(
        **_entry(row, candidate).model_dump(),
        notice=NOTICE,
        total_years=row.evidence["total_years"],
        requirements=[
            RequirementOut(
                keywords=items[result["item"]]["any_of"]
                if result["item"] < len(items)
                else [],
                kind=result["kind"],
                min_years=result["min_years"],
                met=result["met"],
                keyword=result["keyword"],
                years=result["years"],
            )
            for result in row.requirements
        ],
        evidence=[
            KeywordEvidenceOut(
                keyword=fact["keyword"],
                years=fact["years"],
                snippets=[SnippetOut(**snippet) for snippet in fact["snippets"]],
            )
            for fact in row.evidence["keywords"]
            if fact["found"]
        ],
    )
