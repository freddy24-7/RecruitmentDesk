"""The visitor's own workspace: "Reset demo" (PRD section 11)."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.sessions import CurrentWorkspace
from app.db import get_session
from app.vacancy.deletion import ConfirmationRequired, delete_workspace_content
from app.web.errors import ApiError

log = structlog.get_logger()

router = APIRouter()

Db = Annotated[AsyncSession, Depends(get_session)]


class ResetRequest(BaseModel):
    # Destructive: the UI sends true only after its confirmation dialog.
    confirm: bool = False


@router.post("/workspace/reset", status_code=204)
async def reset_demo(
    body: ResetRequest, workspace: CurrentWorkspace, session: Db
) -> None:
    """Delete every vacancy of this workspace, with everything made for it."""
    try:
        await delete_workspace_content(session, workspace.id, confirmed=body.confirm)
    except ConfirmationRequired as missing:
        raise ApiError(
            400,
            "confirmation_required",
            "Resetting the demo needs an explicit confirmation.",
        ) from missing
    await session.commit()
    log.info("workspace.reset", workspace_id=str(workspace.id))
