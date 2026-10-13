"""Putting a failed or interrupted job back in the queue."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import QUEUED, RETRYABLE, Job


async def requeue(session: AsyncSession, job: Job) -> bool:
    """Queue the job again. False if it was not failed or interrupted.

    A conditional update, so a double click queues the job once. The caller
    has checked the limits, commits, and starts the job.
    """
    queued = await session.scalar(
        update(Job)
        .where(Job.id == job.id, Job.status.in_(RETRYABLE))
        .values(
            status=QUEUED,
            attempts=Job.attempts + 1,
            error_kind=None,
            started_at=None,
            finished_at=None,
        )
        .returning(Job.id)
    )
    return queued is not None
