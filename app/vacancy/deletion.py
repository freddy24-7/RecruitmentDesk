"""The one place where vacancy data is deleted (CLAUDE.md rule 8).

"Cancel vacancy" deletes the vacancy and everything that belongs to it.
Replacing candidates deletes the old ones. No other module deletes rows; a
test checks that. Every function here needs an explicit confirmation, which
the UI only sends after its confirmation dialog.
"""

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.candidates.models import Candidate
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
