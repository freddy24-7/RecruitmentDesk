"""Per-IP limit on new sessions (PRD section 11, CLAUDE.md rule 11).

Every session is a fresh workspace with its own budget of generation runs, so
the number of sessions one address may start bounds what one visitor can
spend. Visitors behind one office network share the limit.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import Workspace

WINDOW = timedelta(hours=1)
TOO_MANY_SESSIONS_MESSAGE = (
    "Too many demo sessions were started from this network in the last hour. "
    "Please try again later."
)


async def may_start_session(
    session: AsyncSession, ip_hash: str, per_hour: int, now: datetime
) -> bool:
    """True if this address may start one more session now.

    Takes a transaction-level lock per address first, so simultaneous
    requests from one address are counted one after another. The caller
    creates the workspace and commits in the same transaction.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"session:{ip_hash}"},
    )
    started = await session.scalar(
        select(func.count())
        .select_from(Workspace)
        .where(Workspace.ip_hash == ip_hash, Workspace.created_at > now - WINDOW)
    )
    return (started or 0) < per_hour
