"""Proposing and saving a selection script (PRD F5)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.jobs.models import DONE, Job
from app.jobs.retry import requeue
from app.jobs.runner import JobFailed
from app.limits.workspace import (
    SCRIPT_PROPOSAL,
    check_can_propose_script,
    check_can_retry,
    check_no_job_running,
)
from app.llm.base import LlmError
from app.llm.prompts import load_prompt
from app.llm.service import LlmService
from app.script.models import SelectionScript
from app.script.schemas import Kind, ProposedItem, ScriptItem, ScriptProposal
from app.vacancy.models import SUBMITTED, Vacancy
from app.vacancy.schemas import VacancySections

PROMPT = "script_v2"
CALL = "script"
# A proposal should come out the same when asked twice.
TEMPERATURE = 0.1
MAX_TOKENS = 1500


class NotAllowed(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


def _require_submitted(vacancy: Vacancy) -> None:
    if vacancy.status != SUBMITTED:
        raise NotAllowed(
            "not_submitted", "A selection script needs a submitted vacancy."
        )


# The sections a reason may be quoted from, in the order they are searched.
# Only the first can make a proposed item hard (decided with the author, after
# the stage 6 comparison: requirements taken from the responsibilities were
# proposed as hard, and no planted candidate could meet them).
REQUIRED_SECTION = "required_qualifications"
SECTIONS_SEARCHED = (
    REQUIRED_SECTION,
    "nice_to_haves",
    "responsibilities",
    "role_summary",
    "title",
)
MADE_SOFT = "Proposed as hard, made soft: it is not in the required qualifications."


def _section_texts(sections: VacancySections) -> dict[str, str]:
    texts = {}
    for name in SECTIONS_SEARCHED:
        value = getattr(sections, name)
        texts[name] = "\n".join(value) if isinstance(value, list) else value
    return texts


def vacancy_text(sections: VacancySections) -> str:
    """Everything a script item may be based on, as one text."""
    return "\n".join(_section_texts(sections).values())


def _normalised(text: str) -> str:
    return " ".join(text.lower().split())


def is_grounded(reason: str, text: str) -> bool:
    """True if `reason` is really a piece of `text`.

    The model is asked to quote the vacancy. This is the check in code: the
    quote must be found there, ignoring case, spacing and a final full stop.
    A reason that is not found is kept, but shown as not verified.
    """
    quote = _normalised(reason).rstrip(".")
    return len(quote) >= 8 and quote in _normalised(text)


def find_source(reason: str, sections: VacancySections) -> str:
    """The section of the vacancy the reason is quoted from, or "" if none."""
    for name, text in _section_texts(sections).items():
        if is_grounded(reason, text):
            return name
    return ""


def to_script_items(
    proposal: ScriptProposal, sections: VacancySections
) -> list[ScriptItem]:
    """Turn the model's proposal into script items, each checked against the vacancy.

    Code decides two things here. Whether the reason is really a quote, and
    from which section. And whether the item may be hard: only an item quoted
    from the required qualifications can be. Anything else the model proposed
    as hard becomes soft, with a note that says so.
    """
    return [_to_item(proposed, sections) for proposed in proposal.items]


def _to_item(proposed: ProposedItem, sections: VacancySections) -> ScriptItem:
    source = find_source(proposed.reason, sections)
    hard = proposed.hard and source == REQUIRED_SECTION
    return ScriptItem(
        any_of=proposed.any_of,
        min_years=proposed.min_years,
        kind=Kind.HARD if hard else Kind.SOFT,
        reason=proposed.reason,
        grounded=bool(source),
        source=source,
        note=MADE_SOFT if proposed.hard and not hard else "",
    )


def prompt_variables(sections: VacancySections) -> dict[str, str]:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) or "(none)"

    return {
        "title": sections.title,
        "role_summary": sections.role_summary,
        "responsibilities": bullets(sections.responsibilities),
        "required_qualifications": bullets(sections.required_qualifications),
        "nice_to_haves": bullets(sections.nice_to_haves),
    }


async def start_proposal(
    session: AsyncSession, vacancy: Vacancy, settings: Settings
) -> Job:
    """Create the job that asks the model for a proposal. The caller commits."""
    _require_submitted(vacancy)
    await check_can_propose_script(session, vacancy.workspace_id, settings)
    job = Job(
        workspace_id=vacancy.workspace_id,
        type=SCRIPT_PROPOSAL,
        vacancy_id=vacancy.id,
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    return job


async def retry_proposal(session: AsyncSession, job: Job) -> bool:
    await check_no_job_running(session, job.workspace_id)
    check_can_retry(job.attempts)
    return await requeue(session, job)


class ScriptProposer:
    """The handler for `script_proposal` jobs.

    The proposal is stored with the job, not as a script: nothing is saved as
    the vacancy's script until the recruiter submits the dialog.
    """

    def __init__(self, llm: LlmService, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def __call__(self, session: AsyncSession, job: Job) -> None:
        vacancy = await session.scalar(
            select(Vacancy).where(Vacancy.id == job.vacancy_id)
        )
        if vacancy is None:
            return
        sections = VacancySections.model_validate(vacancy.sections)
        try:
            proposal = await self._llm.generate(
                call_type=CALL,
                model=self._settings.mistral_model_script,
                prompt=load_prompt(PROMPT),
                variables=prompt_variables(sections),
                schema=ScriptProposal,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                workspace_id=vacancy.workspace_id,
                job_id=job.id,
            )
        except LlmError as error:
            raise JobFailed(error.kind) from error

        items = to_script_items(proposal, sections)
        job.result = {
            "vacancy_version": vacancy.version,
            "items": [item.model_dump(mode="json") for item in items],
        }
        job.progress_done = 1


@dataclass(frozen=True)
class Proposal:
    vacancy_version: int
    items: list[dict[str, Any]]


async def latest_proposal(
    session: AsyncSession, vacancy_id: uuid.UUID
) -> Proposal | None:
    """The most recent finished proposal for this vacancy, if any."""
    job = await session.scalar(
        select(Job)
        .where(
            Job.vacancy_id == vacancy_id,
            Job.type == SCRIPT_PROPOSAL,
            Job.status == DONE,
            Job.result.is_not(None),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if job is None or job.result is None:
        return None
    return Proposal(
        vacancy_version=job.result["vacancy_version"], items=job.result["items"]
    )


async def read_script(
    session: AsyncSession, vacancy_id: uuid.UUID
) -> SelectionScript | None:
    script: SelectionScript | None = await session.scalar(
        select(SelectionScript).where(SelectionScript.vacancy_id == vacancy_id)
    )
    return script


async def save_script(
    session: AsyncSession, vacancy: Vacancy, items: list[ScriptItem]
) -> SelectionScript:
    """Save the recruiter's script for the current version of the vacancy.

    The caller commits. Saving is the deliberate action that brings an
    out-of-date script up to date again. Whether a reason is grounded is
    decided here, by code: what the browser sends for it is ignored.
    """
    _require_submitted(vacancy)
    sections = VacancySections.model_validate(vacancy.sections)
    checked = []
    for item in items:
        # What the browser sends for these is ignored: the server decides.
        # The recruiter's own choice of hard or soft is kept as it is.
        source = find_source(item.reason, sections)
        checked.append(
            item.model_copy(
                update={"grounded": bool(source), "source": source, "note": ""}
            )
        )
    stored = [item.model_dump(mode="json") for item in checked]
    now = datetime.now(UTC)
    script = await read_script(session, vacancy.id)
    if script is None:
        script = SelectionScript(
            vacancy_id=vacancy.id,
            vacancy_version=vacancy.version,
            items=stored,
            created_at=now,
            updated_at=now,
        )
        session.add(script)
    else:
        script.items = stored
        script.vacancy_version = vacancy.version
        script.revision += 1
        script.updated_at = now
    await session.flush()
    return script
