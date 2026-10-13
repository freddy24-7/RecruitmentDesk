"""The selection script of a vacancy. Limited to the caller's workspace."""

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.sessions import CurrentWorkspace
from app.config import Settings, get_settings
from app.db import get_session
from app.limits.workspace import LimitReached
from app.script import service
from app.script.schemas import ScriptItem, ScriptItems
from app.vacancy.models import Vacancy
from app.web.errors import ApiError
from app.web.vacancies import JobOut, Runner, job_out, own_vacancy

log = structlog.get_logger()

router = APIRouter()

Db = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


class SavedScript(BaseModel):
    items: list[ScriptItem]
    revision: int
    # True when the vacancy was edited after the script was saved.
    out_of_date: bool
    updated_at: datetime


class ProposalOut(BaseModel):
    items: list[ScriptItem]
    # False when the vacancy was edited after the model made this proposal.
    current: bool


class ScriptOut(BaseModel):
    """What the dialog needs: the saved script, and the model's latest proposal."""

    saved: SavedScript | None
    proposal: ProposalOut | None


async def _script_out(session: AsyncSession, vacancy: Vacancy) -> ScriptOut:
    script = await service.read_script(session, vacancy.id)
    proposal = await service.latest_proposal(session, vacancy.id)
    return ScriptOut(
        saved=SavedScript(
            items=[ScriptItem.model_validate(item) for item in script.items],
            revision=script.revision,
            out_of_date=script.vacancy_version != vacancy.version,
            updated_at=script.updated_at,
        )
        if script
        else None,
        proposal=ProposalOut(
            items=[ScriptItem.model_validate(item) for item in proposal.items],
            current=proposal.vacancy_version == vacancy.version,
        )
        if proposal
        else None,
    )


@router.get("/vacancies/{vacancy_id}/script")
async def read_script(
    vacancy_id: uuid.UUID, workspace: CurrentWorkspace, session: Db
) -> ScriptOut:
    return await _script_out(
        session, await own_vacancy(session, vacancy_id, workspace.id)
    )


@router.post("/vacancies/{vacancy_id}/script/proposal", status_code=202)
async def propose_script(
    vacancy_id: uuid.UUID,
    workspace: CurrentWorkspace,
    session: Db,
    settings: Config,
    runner: Runner,
) -> JobOut:
    """Ask the model for a proposal, in the background. Nothing is saved as script."""
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    try:
        job = await service.start_proposal(session, vacancy, settings)
    except service.NotAllowed as refused:
        raise ApiError(409, refused.kind, refused.message) from refused
    except LimitReached as limit:
        raise ApiError(409, limit.kind, limit.message) from limit
    await session.commit()
    runner.start(job.id)
    log.info("script.proposal_started", vacancy_id=str(vacancy.id))
    return job_out(job)


@router.put("/vacancies/{vacancy_id}/script")
async def save_script(
    vacancy_id: uuid.UUID,
    body: ScriptItems,
    workspace: CurrentWorkspace,
    session: Db,
) -> ScriptOut:
    """Submit the dialog: save the script for the current version of the vacancy."""
    vacancy = await own_vacancy(session, vacancy_id, workspace.id)
    try:
        script = await service.save_script(session, vacancy, body.items)
    except service.NotAllowed as refused:
        raise ApiError(409, refused.kind, refused.message) from refused
    await session.commit()
    log.info(
        "script.saved",
        vacancy_id=str(vacancy.id),
        revision=script.revision,
        items=len(script.items),
    )
    return await _script_out(session, vacancy)
