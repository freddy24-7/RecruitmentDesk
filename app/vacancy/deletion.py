"""The one place where vacancy data is deleted (CLAUDE.md rule 8).

"Cancel vacancy" deletes the vacancy and everything that belongs to it.
Replacing candidates deletes the old ones, and a new screening run deletes
the old lists, and new interview questions the old ones. "Reset demo" and the
clean-up of idle workspaces delete whole workspaces. No other module deletes
rows; a
test checks that. Every function here needs an explicit confirmation, which
the UI only sends after its confirmation dialog.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import FailedAttempt, Workspace
from app.candidates.models import Candidate
from app.interview.models import QuestionSet
from app.screening.models import Assessment
from app.vacancy.models import Vacancy


class ConfirmationRequired(Exception):
    pass


async def delete_vacancy(
    session: AsyncSession, vacancy: Vacancy, *, confirmed: bool
) -> None:
    """Delete the vacancy and all related data. The caller commits.

    Tables that belong to a vacancy reference it with ON DELETE CASCADE, so
    this one statement removes them too. Two kinds of rows are kept on
    purpose, without a link to the vacancy and without any of its content:
    job rows (they count towards the workspace limit) and usage records (the
    model cost was still made).
    """
    if not confirmed:
        raise ConfirmationRequired
    await session.execute(delete(Vacancy).where(Vacancy.id == vacancy.id))


async def delete_candidates(
    session: AsyncSession, vacancy_id: uuid.UUID, *, confirmed: bool
) -> None:
    """Delete all candidates of a vacancy, before new ones replace them.

    The caller commits. Tables that belong to a candidate reference it with
    ON DELETE CASCADE.
    """
    if not confirmed:
        raise ConfirmationRequired
    await session.execute(delete(Candidate).where(Candidate.vacancy_id == vacancy_id))


async def delete_assessments(
    session: AsyncSession, vacancy_id: uuid.UUID, *, confirmed: bool
) -> None:
    """Delete the long list and short list of a vacancy, before a new run.

    The caller commits.
    """
    if not confirmed:
        raise ConfirmationRequired
    await session.execute(delete(Assessment).where(Assessment.vacancy_id == vacancy_id))


async def delete_question_sets(
    session: AsyncSession, vacancy_id: uuid.UUID, *, confirmed: bool
) -> None:
    """Delete the interview questions of a vacancy, before new ones replace them.

    The caller commits.
    """
    if not confirmed:
        raise ConfirmationRequired
    await session.execute(
        delete(QuestionSet).where(QuestionSet.vacancy_id == vacancy_id)
    )


async def delete_workspace_content(
    session: AsyncSession, workspace_id: uuid.UUID, *, confirmed: bool
) -> None:
    """ "Reset demo": delete every vacancy of a workspace, with all related data.

    The workspace and its session stay, and so do its job rows and usage
    records: the limits are not reset. The caller commits.
    """
    if not confirmed:
        raise ConfirmationRequired
    await session.execute(delete(Vacancy).where(Vacancy.workspace_id == workspace_id))


async def delete_idle_workspaces(
    session: AsyncSession, now: datetime, idle: timedelta
) -> int:
    """Delete workspaces nobody used for `idle`, with all their data (PRD section 11).

    Their sessions end with them. Usage records stay, without the link: the
    cost was made. Failed code attempts older than a day go too: the attempt
    limits look back an hour at most. Returns how many workspaces were
    deleted. The caller commits.
    """
    deleted = await session.execute(
        delete(Workspace)
        .where(Workspace.last_seen_at < now - idle)
        .returning(Workspace.id)
    )
    await session.execute(
        delete(FailedAttempt).where(
            FailedAttempt.attempted_at < now - timedelta(days=1)
        )
    )
    return len(deleted.all())
