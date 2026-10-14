"""Screening: from candidates and a script to a long list and a short list (PRD F6).

Two stages. Code computes the facts for every candidate and applies the hard
and soft requirements. The model then assesses the strongest candidates on
their blind CV, and code checks what it says. One run produces both lists.
"""

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.candidates.models import Candidate
from app.candidates.schemas import Cv
from app.config import Settings
from app.jobs.models import DONE, Job
from app.jobs.retry import requeue
from app.jobs.runner import JobFailed
from app.limits.workspace import (
    SCREENING,
    check_can_retry,
    check_can_screen,
    check_no_job_running,
)
from app.llm.base import INVALID_OUTPUT, LlmError
from app.llm.prompts import load_prompt
from app.llm.service import LlmService
from app.screening.blind import blind_cv, blind_text
from app.screening.evidence import check_assessment
from app.screening.facts import CandidateFacts, candidate_facts, script_keywords
from app.screening.models import Assessment
from app.screening.ranking import Scored, build_lists
from app.screening.schemas import ModelAssessment
from app.screening.sizes import list_sizes
from app.script.models import SelectionScript
from app.script.requirements import ItemResult, apply_requirements
from app.script.schemas import ScriptItem
from app.vacancy.deletion import delete_assessments
from app.vacancy.models import SUBMITTED, Vacancy
from app.vacancy.schemas import VacancySections

log = structlog.get_logger()

PROMPT = "assessment_v1"
CALL = "assessment"
# Low, so the same input gives a very similar assessment (PRD F6).
TEMPERATURE = 0.0
MAX_TOKENS = 1200
# The model assesses the strongest candidates: this many times the long list.
ASSESS_FACTOR = 2

MISSED_HARD = "hard_requirement_not_met"


class NotAllowed(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class Inputs:
    """What a screening run needs, and whether each part is up to date."""

    candidates: int
    candidates_out_of_date: bool
    script: SelectionScript | None

    def script_out_of_date(self, vacancy: Vacancy) -> bool:
        return self.script is not None and (
            self.script.vacancy_version != vacancy.version
        )

    def problem(self, vacancy: Vacancy) -> str | None:
        """Why the lists cannot be made now, or None if they can."""
        if self.candidates == 0 and self.script is None:
            return "Generate candidates and a selection script first."
        if self.candidates == 0:
            return "Generate candidates first."
        if self.script is None:
            return "Generate a selection script first."
        if self.candidates_out_of_date:
            return "The candidates are out of date. Generate candidates again first."
        if self.script_out_of_date(vacancy):
            return "The selection script is out of date. Review and submit it first."
        return None


async def read_inputs(session: AsyncSession, vacancy: Vacancy) -> Inputs:
    ready, oldest = (
        await session.execute(
            select(func.count(), func.min(Candidate.vacancy_version)).where(
                Candidate.vacancy_id == vacancy.id, Candidate.cv.is_not(None)
            )
        )
    ).one()
    script = await session.scalar(
        select(SelectionScript).where(SelectionScript.vacancy_id == vacancy.id)
    )
    return Inputs(
        candidates=ready,
        candidates_out_of_date=oldest is not None and oldest != vacancy.version,
        script=script,
    )


@dataclass(frozen=True)
class Run:
    """A finished screening run, as recorded with its job."""

    job_id: uuid.UUID
    created_at: datetime
    result: dict[str, Any]

    def out_of_date(self, vacancy: Vacancy, script: SelectionScript | None) -> bool:
        return (
            self.result["vacancy_version"] != vacancy.version
            or script is None
            or self.result["script_revision"] != script.revision
        )


async def latest_run(session: AsyncSession, vacancy_id: uuid.UUID) -> Run | None:
    """The most recent finished run whose lists still exist."""
    job = await session.scalar(
        select(Job)
        .where(
            Job.vacancy_id == vacancy_id,
            Job.type == SCREENING,
            Job.status == DONE,
            Job.result.is_not(None),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if job is None or job.result is None:
        return None
    # Regenerating candidates deletes the assessments made from the old ones.
    listed = await session.scalar(
        select(func.count())
        .select_from(Assessment)
        .where(Assessment.run_id == job.id, Assessment.in_long_list.is_(True))
    )
    if not listed:
        return None
    return Run(job_id=job.id, created_at=job.created_at, result=job.result)


async def start_screening(
    session: AsyncSession, vacancy: Vacancy, replace: bool, settings: Settings
) -> Job:
    """Create the job for a screening run. The caller commits and starts it.

    A new run replaces the existing lists, which destroys them, so that needs
    `replace=True`. The UI sends it only after its confirmation dialog.
    """
    if vacancy.status != SUBMITTED:
        raise NotAllowed("not_submitted", "Lists need a submitted vacancy.")
    inputs = await read_inputs(session, vacancy)
    problem = inputs.problem(vacancy)
    if problem is not None:
        raise NotAllowed("prerequisites_missing", problem)
    if await latest_run(session, vacancy.id) is not None and not replace:
        raise NotAllowed(
            "replace_confirmation_required",
            "This vacancy already has a long list and a short list. "
            "Generating again replaces them.",
        )
    await check_can_screen(session, vacancy.workspace_id, settings)

    sizes = list_sizes(inputs.candidates)
    assess = min(inputs.candidates, ASSESS_FACTOR * sizes.long)
    job = Job(
        workspace_id=vacancy.workspace_id,
        type=SCREENING,
        vacancy_id=vacancy.id,
        params={"replace": True},
        progress_total=assess,
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    return job


async def retry_screening(session: AsyncSession, job: Job) -> bool:
    await check_no_job_running(session, job.workspace_id)
    check_can_retry(job.attempts)
    return await requeue(session, job)


def criteria_text(items: list[ScriptItem]) -> str:
    """The script as the model reads it."""
    lines = []
    for item in items:
        if not item.enabled:
            continue
        years = f", at least {item.min_years} years" if item.min_years else ""
        lines.append(
            f"- {' or '.join(item.any_of)}{years} "
            f"({'required' if item.kind.value == 'hard' else 'nice to have'})"
        )
    return "\n".join(lines)


def facts_sentence(results: list[ItemResult], items: list[ScriptItem]) -> str:
    """One or two sentences of computed facts, to open the rationale."""
    found = [
        f"{r.keyword} ({r.years:g} years)" if r.years else f"{r.keyword}"
        for r in results
        if r.keyword is not None
    ]
    missing = [" or ".join(items[r.item].any_of) for r in results if r.keyword is None]
    parts = []
    if found:
        parts.append("Found in the CV: " + ", ".join(found) + ".")
    if missing:
        parts.append("Not found: " + ", ".join(missing) + ".")
    return " ".join(parts)


def _missed_flag(result: ItemResult, items: list[ScriptItem]) -> dict[str, str]:
    wanted = " or ".join(items[result.item].any_of)
    if result.keyword is None:
        detail = f"{wanted}: not found in the CV"
    else:
        detail = (
            f"{wanted}: {result.years:g} years of {result.keyword}, "
            f"{result.min_years} asked"
        )
    return {"kind": MISSED_HARD, "detail": detail}


class Screener:
    """The handler for `screening` jobs.

    Idempotent: the facts for all candidates are stored first, then each
    assessment on its own. Running the job again only asks the model for the
    assessments that are still missing.
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
        script = await session.scalar(
            select(SelectionScript).where(SelectionScript.vacancy_id == vacancy.id)
        )
        if script is None:
            raise JobFailed("prerequisites_missing")
        job_id, vacancy_id, workspace_id = job.id, vacancy.id, vacancy.workspace_id
        items = [ScriptItem.model_validate(item) for item in script.items]
        as_of = job.created_at.date()

        prepared = await session.scalar(
            select(func.count())
            .select_from(Assessment)
            .where(Assessment.run_id == job_id)
        )
        if not prepared:
            await self._prepare(session, vacancy, job, items, as_of)
            await session.commit()

        total = (
            await session.scalar(
                select(func.count())
                .select_from(Assessment)
                .where(Assessment.run_id == job_id)
            )
            or 0
        )
        sizes = list_sizes(total)
        assess = min(total, ASSESS_FACTOR * sizes.long)
        waiting = list(
            (
                await session.scalars(
                    select(Assessment.id)
                    .where(
                        Assessment.run_id == job_id,
                        Assessment.deterministic_rank <= assess,
                        Assessment.llm_score.is_(None),
                    )
                    .order_by(Assessment.deterministic_rank)
                )
            ).all()
        )
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(progress_done=assess - len(waiting), progress_total=assess)
        )
        await session.commit()

        variables = self._vacancy_variables(vacancy, items)
        keywords = script_keywords(items)
        slots = asyncio.Semaphore(self._settings.cv_concurrency)
        stop = asyncio.Event()

        async def assess_one(assessment_id: uuid.UUID) -> str | None:
            async with slots:
                if stop.is_set():
                    return None
                try:
                    await self._assess(
                        assessment_id, variables, keywords, as_of, workspace_id, job_id
                    )
                except LlmError as error:
                    if error.kind != INVALID_OUTPUT:
                        stop.set()
                    return error.kind
                return None

        outcomes = await asyncio.gather(*(assess_one(a) for a in waiting))
        failures = [kind for kind in outcomes if kind is not None]
        if failures or stop.is_set():
            systemic = [kind for kind in failures if kind != INVALID_OUTPUT]
            raise JobFailed((systemic or failures or [INVALID_OUTPUT])[0])

        await self._finish(
            session, vacancy, script, job, items, sizes.long, sizes.short
        )
        log.info(
            "screening.finished",
            vacancy_id=str(vacancy_id),
            candidates=total,
            assessed=assess,
            long_list=sizes.long,
            short_list=sizes.short,
        )

    async def _prepare(
        self,
        session: AsyncSession,
        vacancy: Vacancy,
        job: Job,
        items: list[ScriptItem],
        as_of: date,
    ) -> None:
        """Step 1, by code: facts and requirements for every candidate."""
        candidates = (
            await session.scalars(
                select(Candidate)
                .where(Candidate.vacancy_id == vacancy.id, Candidate.cv.is_not(None))
                .order_by(Candidate.number)
            )
        ).all()
        facts: dict[uuid.UUID, CandidateFacts] = {}
        for candidate in candidates:
            # Blind from the first step: facts are computed on the anonymised CV.
            cv = blind_cv(
                Cv.model_validate(candidate.cv),
                name=candidate.name,
                email=candidate.email,
                phone=candidate.phone,
            )
            facts[candidate.id] = candidate_facts(cv, items, as_of)

        sizes = list_sizes(len(candidates))
        # The one place where hard and soft requirements are applied.
        ranked = apply_requirements(
            items,
            {candidate: fact.found_years for candidate, fact in facts.items()},
            needed=sizes.long,
        )

        # The request that created this job carried the confirmation.
        await delete_assessments(session, vacancy.id, confirmed=True)
        now = datetime.now(UTC)
        for rank, entry in enumerate(ranked, start=1):
            session.add(
                Assessment(
                    vacancy_id=vacancy.id,
                    candidate_id=entry.candidate,
                    run_id=job.id,
                    deterministic_score=round(entry.outcome.score, 4),
                    deterministic_rank=rank,
                    meets_hard=entry.outcome.meets_hard,
                    listable=entry.listable,
                    requirements=[
                        asdict(result) | {"kind": result.kind.value}
                        for result in entry.outcome.results
                    ],
                    evidence={
                        "total_years": facts[entry.candidate].total_years,
                        "keywords": [
                            asdict(fact)
                            for fact in facts[entry.candidate].keywords.values()
                        ],
                    },
                    flags=[_missed_flag(r, items) for r in entry.missed_hard],
                    created_at=now,
                )
            )

    def _vacancy_variables(
        self, vacancy: Vacancy, items: list[ScriptItem]
    ) -> dict[str, str]:
        sections = VacancySections.model_validate(vacancy.sections)

        def bullets(lines: list[str]) -> str:
            return "\n".join(f"- {line}" for line in lines) or "(none)"

        return {
            "title": sections.title,
            "role_summary": sections.role_summary,
            "required_qualifications": bullets(sections.required_qualifications),
            "nice_to_haves": bullets(sections.nice_to_haves),
            "criteria": criteria_text(items),
        }

    async def _assess(
        self,
        assessment_id: uuid.UUID,
        vacancy_variables: dict[str, str],
        keywords: list[str],
        as_of: date,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> None:
        """Step 2: one assessment by the model, checked by code, in its own session."""
        async with self._sessionmaker() as session:
            row = await session.get(Assessment, assessment_id)
            if row is None or row.llm_score is not None:
                return
            candidate = await session.get(Candidate, row.candidate_id)
            if candidate is None:
                return
            identifiers = {
                "name": candidate.name,
                "email": candidate.email,
                "phone": candidate.phone,
            }
            cv = blind_cv(Cv.model_validate(candidate.cv), **identifiers)
            # The only form of the CV the model sees: anonymised text. The
            # name and contact details are not passed on in any other way.
            cv_text = blind_text(Cv.model_validate(candidate.cv), **identifiers)

            answer = await self._llm.generate(
                call_type=CALL,
                model=self._settings.mistral_model_assessment,
                prompt=load_prompt(PROMPT),
                variables=vacancy_variables
                | {
                    "cv_text": cv_text,
                    # Not part of the prompt text: the fake model answers from these.
                    "fake_facts_json": json.dumps(row.evidence),
                    "fake_score": str(round(row.deterministic_score * 100)),
                },
                schema=ModelAssessment,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                workspace_id=workspace_id,
                job_id=job_id,
            )

            checked = check_assessment(
                answer,
                cv,
                cv_text,
                keywords,
                as_of,
                total_years=row.evidence["total_years"],
            )
            row.llm_score = checked.fit_score
            row.strengths = checked.strengths
            row.concerns = checked.concerns
            row.reasoning = checked.reasoning
            row.flags = [*row.flags, *(asdict(flag) for flag in checked.flags)]
            row.claims_made = checked.claims_made
            row.claims_supported = checked.claims_supported
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(progress_done=Job.progress_done + 1)
            )
            await session.commit()

    async def _finish(
        self,
        session: AsyncSession,
        vacancy: Vacancy,
        script: SelectionScript,
        job: Job,
        items: list[ScriptItem],
        long_size: int,
        short_size: int,
    ) -> None:
        """Combine the two stages, cut the lists, and record how it was done."""
        rows = (
            await session.scalars(select(Assessment).where(Assessment.run_id == job.id))
        ).all()
        weight = self._settings.screening_weight_deterministic
        lists = build_lists(
            [
                Scored(
                    candidate=row.id,
                    deterministic_score=row.deterministic_score,
                    llm_score=row.llm_score,
                    meets_hard=row.meets_hard,
                    listable=row.listable,
                    missed_hard=sum(
                        1 for flag in row.flags if flag["kind"] == MISSED_HARD
                    ),
                )
                for row in rows
            ],
            list_sizes(len(rows)),
            weight,
        )
        for row in rows:
            row.final_score = lists.scores.get(row.id)
            row.in_long_list = row.id in lists.long
            row.in_short_list = row.id in lists.short
            row.list_position = (
                lists.long.index(row.id) + 1 if row.id in lists.long else None
            )
            if row.llm_score is not None:
                results = [
                    ItemResult(**(result | {"kind": items[result["item"]].kind}))
                    for result in row.requirements
                ]
                row.rationale = " ".join(
                    part
                    for part in (facts_sentence(results, items), row.reasoning or "")
                    if part
                )
        job.result = {
            "vacancy_version": vacancy.version,
            "script_revision": script.revision,
            "candidates": len(rows),
            "assessed": sum(1 for row in rows if row.llm_score is not None),
            "long_size": long_size,
            "short_size": short_size,
            "weight_deterministic": weight,
            "model": self._llm.model_name(self._settings.mistral_model_assessment),
            "prompt_version": PROMPT,
        }
