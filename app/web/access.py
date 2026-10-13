"""The access gate: redeem a code for a session, and read the current session."""

from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.codes import hash_ip
from app.access.models import Workspace
from app.access.service import Redeemed, RedeemFailure, redeem_code
from app.access.sessions import (
    COOKIE_NAME,
    CurrentWorkspace,
    load_workspace,
    set_session_cookie,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.limits.attempts import AttemptLimits, is_locked_out, record_failure
from app.web.errors import ApiError

log = structlog.get_logger()

INVALID_MESSAGE = "That code is not valid. Check the code and try again."
EXHAUSTED_MESSAGE = (
    "This access code has been used the maximum number of times. "
    "Please contact the developer to get a new code."
)
# Says nothing about codes, on purpose.
LOCKED_OUT_MESSAGE = "Too many attempts. Please wait a while and try again."

# The only API route that works without a session.
public_router = APIRouter()
# Included under the session guard in app/main.py.
router = APIRouter()


class RedeemRequest(BaseModel):
    # The code travels in the request body, never in the URL, so it cannot
    # end up in access logs.
    code: str = Field(max_length=64)


class SessionResponse(BaseModel):
    workspace_id: str
    idle_hours: int


def _session_response(workspace: Workspace, settings: Settings) -> SessionResponse:
    return SessionResponse(
        workspace_id=str(workspace.id), idle_hours=settings.session_idle_hours
    )


@public_router.post("/api/session")
async def start_session(
    body: RedeemRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    now = datetime.now(UTC)
    pepper = settings.access_code_pepper.get_secret_value()

    # Someone who is already in does not use up another redemption.
    existing = await load_workspace(
        session, request.cookies.get(COOKIE_NAME), settings, now
    )
    if existing is not None:
        return _session_response(existing, settings)

    ip_hash = hash_ip(request.client.host if request.client else "unknown", pepper)
    limits = AttemptLimits.from_settings(settings)
    if await is_locked_out(session, ip_hash, limits, now):
        log.warning("access.locked_out")
        raise ApiError(
            429,
            "too_many_attempts",
            LOCKED_OUT_MESSAGE,
            headers={"Retry-After": str(int(limits.per_ip_window.total_seconds()))},
        )

    outcome = await redeem_code(session, body.code, pepper, now)

    if not isinstance(outcome, Redeemed):
        await record_failure(session, ip_hash, now)
        await session.commit()
        log.info("access.code_rejected", reason=outcome.value)
        if outcome is RedeemFailure.EXHAUSTED:
            extra = (
                {"contact_url": settings.contact_url} if settings.contact_url else {}
            )
            raise ApiError(403, "code_exhausted", EXHAUSTED_MESSAGE, extra=extra)
        raise ApiError(401, "invalid_code", INVALID_MESSAGE)

    await session.commit()
    set_session_cookie(response, outcome.workspace.id, settings)
    log.info(
        "access.session_started",
        code_label=outcome.code_label,
        workspace_id=str(outcome.workspace.id),
    )
    return _session_response(outcome.workspace, settings)


@router.get("/session")
async def read_session(
    workspace: CurrentWorkspace,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    return _session_response(workspace, settings)
