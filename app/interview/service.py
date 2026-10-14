"""Interview questions for the short list (PRD F8).

Core questions come from the vacancy and its script, and are the same for
every short-listed candidate, so interviews can be compared fairly.
Follow-up questions come from one candidate's blind CV and the assessment
after the evidence check: strengths to verify, concerns to probe. Every
question names what it is based on, and code checks that link.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.candidates.models import Candidate
from app.candidates.schemas import Cv
from app.config import Settings
from app.interview.guardrails import flags_for
from app.interview.models import QuestionSet
from app.interview.schemas import ProposedQuestions, Question, Source
from app.jobs.models import Job
from app.jobs.retry import requeue
from app.jobs.runner import JobFailed
from app.limits.workspace import (
    INTERVIEW_QUESTIONS,
    check_can_make_interview_questions,
    check_can_retry,
    check_no_job_running,
)
from app.llm.base import INVALID_OUTPUT, LlmError
from app.llm.prompts import load_prompt
from app.llm.service import LlmService
from app.screening.blind import blind_text
from app.screening.models import Assessment
from app.screening.service import Run, latest_run
from app.script.models import SelectionScript
from app.script.schemas import ScriptItem
from app.vacancy.deletion import delete_question_sets
from app.vacancy.models import Vacancy
from app.vacancy.schemas import VacancySections

log = structlog.get_logger()

CORE_PROMPT = "interview_core_v2"
FOLLOW_UP_PROMPT = "interview_follow_up_v2"
CALL = "interview"
TEMPERATURE = 0.4
MAX_TOKENS = 1500

BROKEN_LINK = "source_not_found"


class NotAllowed(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class Basis:
    """What a set of questions is made from: the current run and its inputs."""

    run: Run
    script: SelectionScript


async def current_basis(session: AsyncSession, vacancy: Vacancy) -> Basis | str:
    """The current short list and script, or why questions cannot be made now."""
    script = await session.scalar(
        select(SelectionScript).where(SelectionScript.vacancy_id == vacancy.id)
    )
    run = await latest_run(session, vacancy.id)
    if run is None or script is None:
        return "Generate the short list first."
    if run.out_of_date(vacancy, script):
        return "The lists are out of date. Generate them again first."
    return Basis(run=run, script=script)


def out_of_date(
    question_set: QuestionSet, vacancy: Vacancy, basis: Basis | str
) -> bool:
    """True if the vacancy, the script or the lists changed since the set was made."""
    if isinstance(basis, str):
        return True
    return (
        question_set.vacancy_version != vacancy.version
        or question_set.script_revision != basis.script.revision
        or question_set.screening_run_id != basis.run.job_id
    )


async def start_questions(
    session: AsyncSession, vacancy: Vacancy, replace: bool, settings: Settings
) -> Job:
    """Create the job. The caller commits and starts it."""
    basis = await current_basis(session, vacancy)
    if isinstance(basis, str):
        raise NotAllowed("prerequisites_missing", basis)
    existing = await session.scalar(
        select(func.count())
        .select_from(QuestionSet)
        .where(QuestionSet.vacancy_id == vacancy.id)
    )
    if existing and not replace:
        raise NotAllowed(
            "replace_confirmation_required",
            "This vacancy already has interview questions. "
            "Generating again replaces them, with your edits.",
        )
    await check_can_make_interview_questions(session, vacancy.workspace_id, settings)
    short = await _short_listed(session, basis.run.job_id)
    job = Job(
        workspace_id=vacancy.workspace_id,
        type=INTERVIEW_QUESTIONS,
        vacancy_id=vacancy.id,
        progress_total=1 + len(short),
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    return job


async def retry_questions(session: AsyncSession, job: Job) -> bool:
    await check_no_job_running(session, job.workspace_id)
    check_can_retry(job.attempts)
    return await requeue(session, job)


async def _short_listed(session: AsyncSession, run_id: uuid.UUID) -> list[Assessment]:
    return list(
        (
            await session.scalars(
                select(Assessment)
                .where(Assessment.run_id == run_id, Assessment.in_short_list.is_(True))
                .order_by(Assessment.list_position)
            )
        ).all()
    )


def script_sources(script: SelectionScript) -> dict[str, Source]:
    """S1, S2, ...: the enabled items of the script."""
    sources = {}
    for number, raw in enumerate(script.items, start=1):
        item = ScriptItem.model_validate(raw)
        if item.enabled:
            kind = "required" if item.kind.value == "hard" else "nice to have"
            years = f", at least {item.min_years} years" if item.min_years else ""
            text = f"{' or '.join(item.any_of)} ({kind}{years})"
            sources[f"S{number}"] = Source(kind="script_item", text=text)
    return sources


def assessment_sources(assessment: Assessment) -> dict[str, Source]:
    """P1, P2, ... for the strengths and C1, C2, ... for the concerns.

    Only what is left after the evidence check: a question can never rest
    on a claim that was removed as unsupported.
    """
    sources = {
        f"P{n}": Source(kind="strength", text=text)
        for n, text in enumerate(assessment.strengths, start=1)
    }
    sources |= {
        f"C{n}": Source(kind="concern", text=text)
        for n, text in enumerate(assessment.concerns, start=1)
    }
    return sources


def _listing(sources: dict[str, Source]) -> str:
    return "\n".join(f"{ref}: {source.text}" for ref, source in sources.items())


def link_questions(
    proposed: ProposedQuestions, sources: dict[str, Source]
) -> tuple[list[Question], list[dict[str, str]]]:
    """Keep the questions whose source exists; drop and report the others."""
    kept: list[Question] = []
    dropped: list[dict[str, str]] = []
    for item in proposed.questions:
        source = sources.get(item.source)
        if source is None:
            dropped.append({"kind": BROKEN_LINK, "detail": item.source or "(none)"})
            continue
        kept.append(
            Question(
                question=item.question,
                purpose=item.purpose,
                source=item.source,
                source_kind=source.kind,
                source_text=source.text,
                flags=flags_for(f"{item.question} {item.purpose}"),
            )
        )
    return kept, dropped


def recheck(questions: list[Question], sources: dict[str, Any]) -> list[Question]:
    """For a set the recruiter edited: the server decides sources and flags.

    A reference that is not one of the set's sources makes the question the
    recruiter's own. What the browser sends for the source text and the flags
    is ignored.
    """
    checked = []
    for question in questions:
        source = sources.get(question.source) if question.source else None
        checked.append(
            question.model_copy(
                update={
                    "source": question.source if source else "",
                    "source_kind": source["kind"] if source else "recruiter",
                    "source_text": source["text"] if source else "",
                    "flags": flags_for(f"{question.question} {question.purpose}"),
                }
            )
        )
    return checked


class InterviewQuestioner:
    """The handler for `interview_questions` jobs.

    Idempotent: each set is stored as soon as it is made. Running the job
    again only makes the sets that are still missing.
    """

    def __init__(
        self,
        llm: LlmService,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self._llm = llm
        self._settings = settings
        self._sessionmaker = sessionmaker

    async def __call__(self, session: AsyncSession, job: Job) -> None:
        vacancy = await session.scalar(
            select(Vacancy).where(Vacancy.id == job.vacancy_id)
        )
        if vacancy is None:
            return
        basis = await current_basis(session, vacancy)
        if isinstance(basis, str):
            raise JobFailed("prerequisites_missing")
        job_id = job.id

        made = (
            await session.scalars(
                select(QuestionSet).where(QuestionSet.job_id == job_id)
            )
        ).all()
        if not made:
            # The request that created this job carried the confirmation.
            await delete_question_sets(session, vacancy.id, confirmed=True)
            await session.commit()
        have_core = any(s.candidate_id is None for s in made)
        have_follow_up = {s.candidate_id for s in made if s.candidate_id is not None}

        sections = VacancySections.model_validate(vacancy.sections)
        common = {
            "title": sections.title,
            "role_summary": sections.role_summary,
            "required_qualifications": "\n".join(
                f"- {line}" for line in sections.required_qualifications
            ),
        }
        stamp = {
            "vacancy_id": vacancy.id,
            "job_id": job_id,
            "vacancy_version": vacancy.version,
            "script_revision": basis.script.revision,
            "screening_run_id": basis.run.job_id,
        }
        script = script_sources(basis.script)
        short = await _short_listed(session, basis.run.job_id)
        await session.commit()

        tasks = []
        if not have_core:
            tasks.append(
                self._make_set(
                    None,
                    CORE_PROMPT,
                    common | {"criteria": _listing(script)},
                    script,
                    stamp,
                    vacancy.workspace_id,
                )
            )
        for assessment in short:
            if assessment.candidate_id in have_follow_up:
                continue
            tasks.append(
                self._follow_ups(
                    assessment, common, script, stamp, vacancy.workspace_id
                )
            )

        slots = asyncio.Semaphore(self._settings.cv_concurrency)

        async def guarded(task: Any) -> str | None:
            async with slots:
                try:
                    await task
                except LlmError as error:
                    return error.kind
                return None

        failures = [k for k in await asyncio.gather(*(guarded(t) for t in tasks)) if k]
        if failures:
            systemic = [kind for kind in failures if kind != INVALID_OUTPUT]
            raise JobFailed((systemic or failures)[0])
        log.info("interview.finished", vacancy_id=str(vacancy.id), sets=1 + len(short))

    async def _follow_ups(
        self,
        assessment: Assessment,
        common: dict[str, str],
        script: dict[str, Source],
        stamp: dict[str, Any],
        workspace_id: uuid.UUID,
    ) -> None:
        async with self._sessionmaker() as session:
            candidate = await session.get(Candidate, assessment.candidate_id)
        if candidate is None:
            return
        # The model reads the anonymised CV only. The name is joined back
        # when the questions are displayed.
        cv_text = blind_text(
            Cv.model_validate(candidate.cv),
            name=candidate.name,
            email=candidate.email,
            phone=candidate.phone,
        )
        points = assessment_sources(assessment)
        await self._make_set(
            candidate.id,
            FOLLOW_UP_PROMPT,
            common | {"cv_text": cv_text, "points": _listing(points) or "(none)"},
            points,
            stamp,
            workspace_id,
        )

    async def _make_set(
        self,
        candidate_id: uuid.UUID | None,
        prompt_version: str,
        variables: dict[str, str],
        sources: dict[str, Source],
        stamp: dict[str, Any],
        workspace_id: uuid.UUID,
    ) -> None:
        """One model call, its links checked, stored in a session of its own."""
        proposed = await self._llm.generate(
            call_type=CALL,
            model=self._settings.mistral_model_interview,
            prompt=load_prompt(prompt_version),
            # The references are passed on for the fake model, which answers
            # from them; they are not part of the prompt text twice.
            variables=variables | {"fake_refs": ",".join(sources)},
            schema=ProposedQuestions,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            workspace_id=workspace_id,
            job_id=stamp["job_id"],
        )
        questions, dropped = link_questions(proposed, sources)
        stored = [question.model_dump(mode="json") for question in questions]
        now = datetime.now(UTC)
        async with self._sessionmaker() as session:
            session.add(
                QuestionSet(
                    candidate_id=candidate_id,
                    sources={ref: s.model_dump() for ref, s in sources.items()},
                    questions=stored,
                    generated_questions=stored,
                    dropped=dropped,
                    prompt_version=prompt_version,
                    created_at=now,
                    updated_at=now,
                    **stamp,
                )
            )
            # Atomic: the sets are made side by side.
            await session.execute(
                update(Job)
                .where(Job.id == stamp["job_id"])
                .values(progress_done=Job.progress_done + 1)
            )
            await session.commit()
