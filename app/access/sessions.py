"""The session cookie and the dependency that guards every protected route."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Workspace
from app.config import Settings, get_settings
from app.db import get_session
from app.web.errors import ApiError

COOKIE_NAME = "rd_session"
# last_seen_at is written at most this often, not on every request.
TOUCH_INTERVAL = timedelta(minutes=1)


def _serializer(settings: Settings) -> URLSafeSerializer:
    return URLSafeSerializer(
        settings.session_secret.get_secret_value(), salt="recruitdesk.session"
    )


def sign_workspace_id(workspace_id: uuid.UUID, settings: Settings) -> str:
    return _serializer(settings).dumps(str(workspace_id))


def read_workspace_id(token: str | None, settings: Settings) -> uuid.UUID | None:
    """Return the workspace id from a cookie value, or None if it is not ours."""
    if not token:
        return None
    try:
        return uuid.UUID(_serializer(settings).loads(token))
    except (BadSignature, ValueError, TypeError, AttributeError):
        return None


def set_session_cookie(
    response: Response, workspace_id: uuid.UUID, settings: Settings
) -> None:
    response.set_cookie(
        COOKIE_NAME,
        sign_workspace_id(workspace_id, settings),
        max_age=settings.session_idle_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


async def load_workspace(
    session: AsyncSession, token: str | None, settings: Settings, now: datetime
) -> Workspace | None:
    """The workspace for this cookie, if it exists and has not been idle too long."""
    workspace_id = read_workspace_id(token, settings)
    if workspace_id is None:
        return None
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return None
    if now - workspace.last_seen_at > timedelta(hours=settings.session_idle_hours):
        return None
    return workspace


async def require_workspace(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Workspace:
    """Dependency for every protected route: a valid session, or 401."""
    now = datetime.now(UTC)
    workspace = await load_workspace(
        session, request.cookies.get(COOKIE_NAME), settings, now
    )
    if workspace is None:
        raise ApiError(401, "no_session", "Enter an access code to continue.")

    if now - workspace.last_seen_at > TOUCH_INTERVAL:
        # Activity keeps the session alive: move the idle deadline forward.
        workspace.last_seen_at = now
        await session.commit()
        set_session_cookie(response, workspace.id, settings)
    return workspace


CurrentWorkspace = Annotated[Workspace, Depends(require_workspace)]
