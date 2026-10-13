"""Per-workspace limits on billable work (PRD F0 "bounded spend", section 11).

Each stage that adds a billable step adds its limit here, so the worst-case
spend of one session stays a number that can be computed.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.jobs.models import ACTIVE, Job

VACANCY_GENERATION = "vacancy_generation"


class LimitReached(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


async def check_can_generate_vacancy(
    session: AsyncSession, workspace_id: uuid.UUID, settings: Settings
) -> None:
    """Raise LimitReached if this workspace may not start another generation."""
    active = await session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.workspace_id == workspace_id, Job.status.in_(ACTIVE))
    )
    if active:
        raise LimitReached(
            "job_in_progress",
            "Another job is still running. Wait until it has finished.",
        )

    # Starts are counted, not vacancies: a retry costs model calls too, and
    # deleting a vacancy does not give the budget back.
    starts = await session.scalar(
        select(func.coalesce(func.sum(Job.attempts), 0)).where(
            Job.workspace_id == workspace_id, Job.type == VACANCY_GENERATION
        )
    )
    limit = settings.max_vacancy_generations_per_workspace
    if (starts or 0) >= limit:
        raise LimitReached(
            "limit_reached",
            f"This demo workspace has used all {limit} vacancy generations.",
        )
