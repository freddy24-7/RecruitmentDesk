"""The daily global spend cap (PRD section 11).

A second protection behind the per-session limits: whatever happens, the
model calls of all workspaces together cost at most this much per day (UTC).
The cost figures come from the usage records. When the cap is reached,
generation is switched off until midnight UTC, with a clear message.
"""

from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.usage import UsageRecord

SPEND_CAP_MESSAGE = (
    "The demo has reached its budget for today. Generation is switched off "
    "until midnight (UTC). Everything else keeps working."
)


async def spent_today(session: AsyncSession, now: datetime | None = None) -> Decimal:
    """Estimated cost of all model calls since midnight UTC."""
    now = now or datetime.now(UTC)
    midnight = datetime.combine(now.date(), time(0), tzinfo=UTC)
    spent = await session.scalar(
        select(func.coalesce(func.sum(UsageRecord.estimated_cost), 0)).where(
            UsageRecord.created_at >= midnight
        )
    )
    return Decimal(spent or 0)


async def cap_reached(
    session: AsyncSession, cap: Decimal | None, now: datetime | None = None
) -> bool:
    """True when today's spend has reached the cap. No cap means no limit."""
    if cap is None:
        return False
    return await spent_today(session, now) >= cap
