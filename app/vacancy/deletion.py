"""The one deletion path for a vacancy (CLAUDE.md rule 8).

"Cancel vacancy" deletes the vacancy and everything that belongs to it. No
other module deletes vacancy data; a test checks that. The caller must pass
an explicit confirmation, which the UI only sends after its confirmation
dialog.
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

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
