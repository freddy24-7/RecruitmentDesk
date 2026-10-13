"""Runs jobs as asyncio tasks in the web process (PRD section 8).

Enough for a demo with one process. The price is that a restart stops
running jobs: `mark_interrupted_jobs` marks them at startup, and the user
can run them again (CLAUDE.md rule 10).
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs.models import (
    ACTIVE,
    DONE,
    ERROR_INTERNAL,
    ERROR_INTERRUPTED,
    FAILED,
    INTERRUPTED,
    QUEUED,
    RUNNING,
    Job,
)

log = structlog.get_logger()

# A handler does the work of one job type. It gets its own database session.
Handler = Callable[[AsyncSession, Job], Awaitable[None]]


class JobFailed(Exception):
    """Raised by a handler for an expected failure, with an error kind."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class JobRunner:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        handlers: dict[str, Handler],
    ) -> None:
        self._sessionmaker = sessionmaker
        self._handlers = handlers
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, job_id: uuid.UUID) -> None:
        """Run a queued job in the background and return at once."""
        task = asyncio.create_task(self._run(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Wait until all running jobs have finished. Used by tests."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _run(self, job_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session:
            # Claim the job with a conditional update. Starting the same job
            # twice therefore runs it once.
            claimed = await session.scalar(
                update(Job)
                .where(Job.id == job_id, Job.status == QUEUED)
                .values(status=RUNNING, started_at=datetime.now(UTC), finished_at=None)
                .returning(Job)
            )
            await session.commit()
            if claimed is None:
                return
            job: Job = claimed
            job_type = job.type

            error_kind: str | None = None
            try:
                await self._handlers[job_type](session, job)
                await session.commit()
            except JobFailed as failure:
                error_kind = failure.kind
            except Exception as error:
                error_kind = ERROR_INTERNAL
                # The exception type only: its message could contain content.
                log.error(
                    "job.crashed",
                    job_id=str(job_id),
                    job_type=job_type,
                    exception=type(error).__name__,
                )

            if error_kind is not None:
                await session.rollback()
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(
                    status=DONE if error_kind is None else FAILED,
                    error_kind=error_kind,
                    finished_at=datetime.now(UTC),
                )
            )
            await session.commit()
            log.info(
                "job.finished",
                job_id=str(job_id),
                job_type=job_type,
                status=DONE if error_kind is None else FAILED,
                error_kind=error_kind,
            )


async def mark_interrupted_jobs(session: AsyncSession) -> int:
    """At startup: jobs that were queued or running did not survive the restart."""
    result = await session.execute(
        update(Job)
        .where(Job.status.in_(ACTIVE))
        .values(
            status=INTERRUPTED,
            error_kind=ERROR_INTERRUPTED,
            finished_at=datetime.now(UTC),
        )
        .returning(Job.id)
    )
    return len(result.all())
