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
CANDIDATE_GENERATION = "candidate_generation"
SCRIPT_PROPOSAL = "script_proposal"
SCREENING = "screening"
# A failing job cannot be retried for ever: each try can cost model calls.
MAX_ATTEMPTS_PER_JOB = 3


class LimitReached(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


async def check_no_job_running(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """One job at a time per workspace."""
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


async def check_can_generate_vacancy(
    session: AsyncSession, workspace_id: uuid.UUID, settings: Settings
) -> None:
    """Raise LimitReached if this workspace may not start another generation."""
    await check_no_job_running(session, workspace_id)

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


async def check_can_generate_candidates(
    session: AsyncSession, workspace_id: uuid.UUID, count: int, settings: Settings
) -> None:
    """Raise LimitReached if this workspace may not generate `count` more candidates."""
    await check_no_job_running(session, workspace_id)

    # Requested candidates are counted, over all vacancies of the workspace.
    # Replacing or deleting candidates does not give the budget back.
    requested = await session.scalar(
        select(func.coalesce(func.sum(Job.progress_total), 0)).where(
            Job.workspace_id == workspace_id, Job.type == CANDIDATE_GENERATION
        )
    )
    limit = settings.max_candidates_per_workspace
    left = limit - (requested or 0)
    if count > left:
        raise LimitReached(
            "limit_reached",
            f"This demo workspace can generate {limit} candidates in total. "
            f"There is room for {max(left, 0)} more.",
        )


async def check_can_propose_script(
    session: AsyncSession, workspace_id: uuid.UUID, settings: Settings
) -> None:
    """Raise LimitReached if this workspace may not ask for another proposal."""
    await check_no_job_running(session, workspace_id)
    starts = await session.scalar(
        select(func.coalesce(func.sum(Job.attempts), 0)).where(
            Job.workspace_id == workspace_id, Job.type == SCRIPT_PROPOSAL
        )
    )
    limit = settings.max_script_proposals_per_workspace
    if (starts or 0) >= limit:
        raise LimitReached(
            "limit_reached",
            f"This demo workspace has used all {limit} script proposals. "
            "You can still edit and save the script by hand.",
        )


async def check_can_screen(
    session: AsyncSession, workspace_id: uuid.UUID, settings: Settings
) -> None:
    """Raise LimitReached if this workspace may not start another screening run."""
    await check_no_job_running(session, workspace_id)
    starts = await session.scalar(
        select(func.coalesce(func.sum(Job.attempts), 0)).where(
            Job.workspace_id == workspace_id, Job.type == SCREENING
        )
    )
    limit = settings.max_screening_runs_per_workspace
    if (starts or 0) >= limit:
        raise LimitReached(
            "limit_reached",
            f"This demo workspace has used all {limit} screening runs.",
        )


def check_can_retry(attempts: int) -> None:
    if attempts >= MAX_ATTEMPTS_PER_JOB:
        raise LimitReached(
            "limit_reached",
            f"This job was already tried {MAX_ATTEMPTS_PER_JOB} times. "
            "Start a new one instead.",
        )
