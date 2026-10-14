"""Interview questions of a vacancy. Limited to the caller's workspace.

Candidate names are joined back here, for display only: the model wrote the
follow-up questions from an anonymised CV.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.sessions import CurrentWorkspace
from app.candidates.models import Candidate
from app.config import Settings, get_settings
from app.db import get_session
from app.interview import service
from app.interview.models import QuestionSet
from app.interview.schemas import Question, QuestionsIn
from app.limits.workspace import LimitReached
from app.screening.models import Assessment
from app.vacancy.models import Vacancy
from app.web.errors import ApiError
from app.web.screening import NOTICE
from app.web.vacancies import JobOut, Runner, job_out, own_vacancy

log = structlog.get_logger()

router = APIRouter()

Db = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


class StartRequest(BaseModel):
    # Must be true when questions already exist: they will be replaced.
    replace: bool = False


class DroppedOut(BaseModel):
    kind: str
    detail: str


class SetOut(BaseModel):
    id: uuid.UUID
    # Empty for the core questions.
    candidate_id: uuid.UUID | None
    candidate_name: str | None
    list_position: int | None
    questions: list[Question]
    # True when the recruiter changed the questions the model wrote.
    edited: bool
    # Questions the model wrote that were dropped, because their source did
    # not exist.
    dropped: list[DroppedOut]


class InterviewOut(BaseModel):
    notice: str
    vacancy_title: str
    out_of_date: bool
    core: SetOut | None
    follow_ups: list[SetOut]


async def _sets(
    session: AsyncSession, vacancy: Vacancy
) -> tuple[list[tuple[QuestionSet, Candidate | None]], bool]:
    rows = (
        await session.execute(
            select(QuestionSet, Candidate)
            .outerjoin(Candidate, Candidate.id == QuestionSet.candidate_id)
            .where(QuestionSet.vacancy_id == vacancy.id)
        )
    ).all()
    basis = await service.current_basis(session, vacancy)
    sets: list[tuple[QuestionSet, Candidate | None]] = [
        (row[0], row[1]) for row in rows
    ]
    stale = any(service.out_of_date(s, vacancy, basis) for s, _ in sets)
    return sets, stale


async def _positions(session: AsyncSession, vacancy: Vacancy) -> dict[uuid.UUID, int]:
    basis = await service.current_basis(session, vacancy)
    if isinstance(basis, str):
        return {}
    rows = (
        await session.execute(
            select(Assessment.candidate_id, Assessment.list_position).where(
                Assessment.run_id == basis.run.job_id,
                Assessment.in_short_list.is_(True),
            )
        )
    ).all()
    return {row[0]: row[1] for row in rows if row[1] is not None}


def _set_out(
    question_set: QuestionSet, candidate: Candidate | None, position: int | None
) -> SetOut:
    return SetOut(
        id=question_set.id,
        candidate_id=question_set.candidate_id,
        candidate_name=candidate.name if candidate else None,
        list_position=position,
        questions=[Question.model_validate(q) for q in question_set.questions],
        edited=question_set.questions != question_set.generated_questions,
        dropped=[DroppedOut(**d) for d in question_set.dropped],
    )


@router.post("/vacancies/{vacancy_id}/interview", status_code=202)
async def start_questions(
    vacancy_id: uuid.UUID,
    body: StartRequest,
    workspace: CurrentWorkspace,
    session: Db,
    settings: Config,
    runner: Runner,
) -> JobOut:
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    try:
        job = await service.start_questions(session, vacancy, body.replace, settings)
    except service.NotAllowed as refused:
        raise ApiError(409, refused.kind, refused.message) from refused
    except LimitReached as limit:
        raise ApiError(409, limit.kind, limit.message) from limit
    await session.commit()
    runner.start(job.id)
    log.info("interview.started", vacancy_id=str(vacancy.id))
    return job_out(job)


@router.get("/vacancies/{vacancy_id}/interview")
async def read_questions(
    vacancy_id: uuid.UUID, workspace: CurrentWorkspace, session: Db
) -> InterviewOut:
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    sets, stale = await _sets(session, vacancy)
    if not sets:
        raise ApiError(
            404, "no_questions", "No interview questions have been made yet."
        )
    positions = await _positions(session, vacancy)
    core = next((s for s, c in sets if s.candidate_id is None), None)
    follow_ups = sorted(
        (
            _set_out(s, c, positions.get(s.candidate_id) if s.candidate_id else None)
            for s, c in sets
            if s.candidate_id is not None
        ),
        key=lambda out: out.list_position or 99,
    )
    return InterviewOut(
        notice=NOTICE,
        vacancy_title=str((vacancy.sections or {}).get("title", "")),
        out_of_date=stale,
        core=_set_out(core, None, None) if core else None,
        follow_ups=follow_ups,
    )


async def _own_set(
    session: AsyncSession, vacancy: Vacancy, set_id: uuid.UUID
) -> QuestionSet:
    found = await session.scalar(
        select(QuestionSet).where(
            QuestionSet.id == set_id, QuestionSet.vacancy_id == vacancy.id
        )
    )
    if found is None:
        raise ApiError(404, "not_found", "These questions do not exist.")
    return found


async def _one_out(session: AsyncSession, question_set: QuestionSet) -> SetOut:
    candidate = (
        await session.get(Candidate, question_set.candidate_id)
        if question_set.candidate_id
        else None
    )
    return _set_out(question_set, candidate, None)


@router.put("/vacancies/{vacancy_id}/interview/{set_id}")
async def save_questions(
    vacancy_id: uuid.UUID,
    set_id: uuid.UUID,
    body: QuestionsIn,
    workspace: CurrentWorkspace,
    session: Db,
) -> SetOut:
    """Save the recruiter's edits: changed, removed and added questions."""
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    question_set = await _own_set(session, vacancy, set_id)
    checked = service.recheck(body.questions, question_set.sources)
    question_set.questions = [q.model_dump(mode="json") for q in checked]
    question_set.updated_at = datetime.now(UTC)
    await session.commit()
    log.info("interview.edited", set_id=str(set_id), questions=len(checked))
    return await _one_out(session, question_set)


@router.post("/vacancies/{vacancy_id}/interview/{set_id}/reset")
async def reset_questions(
    vacancy_id: uuid.UUID,
    set_id: uuid.UUID,
    workspace: CurrentWorkspace,
    session: Db,
) -> SetOut:
    """Go back to the questions as the model wrote them. Edits are lost."""
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    question_set = await _own_set(session, vacancy, set_id)
    question_set.questions = question_set.generated_questions
    question_set.updated_at = datetime.now(UTC)
    await session.commit()
    return await _one_out(session, question_set)
