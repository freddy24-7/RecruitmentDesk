"""Generating candidates: blueprints by code, CVs by the model (PRD F4)."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.candidates.blueprints import sample_blueprints
from app.candidates.cv import assemble, problems_in, render_text
from app.candidates.models import Candidate
from app.candidates.schemas import (
    MAX_CANDIDATES,
    Blueprint,
    CvText,
    VacancyProfile,
)
from app.config import Settings
from app.jobs.models import Job
from app.jobs.retry import requeue
from app.jobs.runner import JobFailed
from app.limits.workspace import (
    CANDIDATE_GENERATION,
    check_can_generate_candidates,
    check_can_retry,
    check_no_job_running,
)
from app.llm.base import INVALID_OUTPUT, LlmError
from app.llm.prompts import load_prompt
from app.llm.service import LlmService
from app.vacancy.deletion import delete_candidates
from app.vacancy.models import SUBMITTED, Vacancy
from app.vacancy.schemas import VacancyParameters, VacancySections

log = structlog.get_logger()

PROFILE_PROMPT = "vacancy_profile_v1"
CV_PROMPT = "cv_v1"
PROFILE_CALL = "vacancy_profile"
CV_CALL = "cv"
# Extraction should be repeatable; CV prose may vary.
PROFILE_TEMPERATURE = 0.1
CV_TEMPERATURE = 0.8
PROFILE_MAX_TOKENS = 1500
CV_MAX_TOKENS = 1500


class NotAllowed(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


async def count_candidates(session: AsyncSession, vacancy_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Candidate)
        .where(Candidate.vacancy_id == vacancy_id)
    )
    return count or 0


async def start_generation(
    session: AsyncSession,
    vacancy: Vacancy,
    count: int,
    replace: bool,
    settings: Settings,
) -> Job:
    """Create the job for `count` new candidates. The caller commits and starts it.

    Existing candidates are replaced, which destroys them, so that needs
    `replace=True`. The UI sends it only after its confirmation dialog.
    """
    # The cap is enforced here on the server, not only in the form.
    if not 1 <= count <= MAX_CANDIDATES:
        raise NotAllowed(
            "invalid_count", f"Choose a number from 1 to {MAX_CANDIDATES}."
        )
    if vacancy.status != SUBMITTED:
        raise NotAllowed(
            "not_submitted", "Candidates can be generated for a submitted vacancy."
        )
    existing = await count_candidates(session, vacancy.id)
    if existing and not replace:
        raise NotAllowed(
            "replace_confirmation_required",
            f"This vacancy already has {existing} candidates. "
            "Generating again replaces them.",
        )
    await check_can_generate_candidates(session, vacancy.workspace_id, count, settings)

    # A new run gets a new seed, so regenerating gives different people. The
    # seed is stored with the job, so any pool can be reproduced.
    earlier_runs = await session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.vacancy_id == vacancy.id, Job.type == CANDIDATE_GENERATION)
    )
    job = Job(
        workspace_id=vacancy.workspace_id,
        type=CANDIDATE_GENERATION,
        vacancy_id=vacancy.id,
        params={"count": count, "seed": settings.blueprint_seed + (earlier_runs or 0)},
        progress_total=count,
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    return job


async def retry_generation(session: AsyncSession, job: Job) -> bool:
    """Queue a failed or interrupted job again. It only writes the CVs still missing."""
    await check_no_job_running(session, job.workspace_id)
    check_can_retry(job.attempts)
    return await requeue(session, job)


def profile_variables(vacancy: Vacancy) -> dict[str, str]:
    sections = VacancySections.model_validate(vacancy.sections)
    parameters = VacancyParameters.model_validate(vacancy.parameters)

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) or "(none)"

    return {
        "title": sections.title,
        "sector": parameters.sector.value,
        "role_summary": sections.role_summary,
        "responsibilities": bullets(sections.responsibilities),
        "required_qualifications": bullets(sections.required_qualifications),
        "nice_to_haves": bullets(sections.nice_to_haves),
    }


def cv_variables(blueprint: Blueprint, sector: str) -> dict[str, str]:
    """What the model is told about a candidate. No name and no contact details."""
    jobs = [
        f"{number}. {position.role} ({position.seniority}), "
        f"{position.start} to {position.end or 'present'}. "
        f"Skills in this job: {', '.join(position.skills) or 'none in particular'}"
        for number, position in enumerate(blueprint.positions, start=1)
    ]
    return {
        "sector": sector,
        "seniority": blueprint.seniority,
        "years_experience": f"{blueprint.years_experience:g}",
        "education_level": blueprint.education_level,
        "positions": "\n".join(jobs),
        "avoid_skills": ", ".join(blueprint.avoid_skills) or "(nothing)",
        # Not part of the prompt text: the fake model answers from this.
        "positions_json": json.dumps(
            [
                {"role": p.role, "seniority": p.seniority, "skills": p.skills}
                for p in blueprint.positions
            ]
        ),
    }


class CandidateGenerator:
    """The handler for `candidate_generation` jobs.

    Idempotent: the blueprints are stored first, then each CV is written
    and stored on its own. Running the job again only writes the CVs that
    are still missing.
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
        if vacancy is None or job.params is None:
            return
        job_id, vacancy_id, workspace_id = job.id, vacancy.id, vacancy.workspace_id
        sector = VacancyParameters.model_validate(vacancy.parameters).sector.value

        try:
            profile = await self._profile(vacancy, job_id)
        except LlmError as error:
            raise JobFailed(error.kind) from error
        await session.commit()

        planned = await session.scalar(
            select(func.count())
            .select_from(Candidate)
            .where(Candidate.job_id == job_id)
        )
        if not planned:
            await self._plan(session, vacancy, job, profile)
            await session.commit()

        waiting = list(
            (
                await session.scalars(
                    select(Candidate.id)
                    .where(Candidate.job_id == job_id, Candidate.cv.is_(None))
                    .order_by(Candidate.number)
                )
            ).all()
        )
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(progress_done=job.params["count"] - len(waiting))
        )
        await session.commit()

        # Limited concurrency: a burst of 100 calls would hit the rate limit.
        slots = asyncio.Semaphore(self._settings.cv_concurrency)
        # Set when the model is unreachable or refuses: no point in going on.
        stop = asyncio.Event()

        async def write(candidate_id: uuid.UUID) -> str | None:
            async with slots:
                if stop.is_set():
                    return None
                try:
                    await self._write_cv(candidate_id, sector, workspace_id, job_id)
                except LlmError as error:
                    if error.kind != INVALID_OUTPUT:
                        stop.set()
                    return error.kind
                return None

        outcomes = await asyncio.gather(*(write(candidate) for candidate in waiting))
        failures = [kind for kind in outcomes if kind is not None]
        log.info(
            "candidates.generated",
            vacancy_id=str(vacancy_id),
            requested=job.params["count"],
            failed=len(failures),
        )
        if failures or stop.is_set():
            # Systemic failures (rate limit, no key) say more than one bad answer.
            systemic = [kind for kind in failures if kind != INVALID_OUTPUT]
            raise JobFailed((systemic or failures or [INVALID_OUTPUT])[0])

    async def _profile(self, vacancy: Vacancy, job_id: uuid.UUID) -> VacancyProfile:
        """Skills and neighbouring roles of the vacancy: one model call per version."""
        if vacancy.profile is not None and vacancy.profile_version == vacancy.version:
            return VacancyProfile.model_validate(vacancy.profile)
        profile = await self._llm.generate(
            call_type=PROFILE_CALL,
            model=self._settings.mistral_model_vacancy,
            prompt=load_prompt(PROFILE_PROMPT),
            variables=profile_variables(vacancy),
            schema=VacancyProfile,
            temperature=PROFILE_TEMPERATURE,
            max_tokens=PROFILE_MAX_TOKENS,
            workspace_id=vacancy.workspace_id,
            job_id=job_id,
        )
        vacancy.profile = profile.model_dump(mode="json")
        vacancy.profile_version = vacancy.version
        return profile

    async def _plan(
        self, session: AsyncSession, vacancy: Vacancy, job: Job, profile: VacancyProfile
    ) -> None:
        """Replace the vacancy's candidates by freshly sampled blueprints."""
        assert job.params is not None  # noqa: S101 - checked by the caller
        parameters = VacancyParameters.model_validate(vacancy.parameters)
        blueprints = sample_blueprints(
            n=job.params["count"],
            seed=job.params["seed"],
            title=parameters.title,
            seniority=[level.value for level in parameters.seniority],
            profile=profile,
            as_of=job.created_at.date(),
        )
        # The request that created this job carried the confirmation.
        await delete_candidates(session, vacancy.id, confirmed=True)
        now = datetime.now(UTC)
        session.add_all(
            Candidate(
                vacancy_id=vacancy.id,
                job_id=job.id,
                vacancy_version=vacancy.version,
                number=blueprint.index,
                blueprint=blueprint.model_dump(mode="json"),
                name=blueprint.name,
                email=blueprint.email,
                phone=blueprint.phone,
                created_at=now,
            )
            for blueprint in blueprints
        )

    async def _write_cv(
        self,
        candidate_id: uuid.UUID,
        sector: str,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> None:
        """Write and store one CV, in its own session: the calls run side by side."""
        async with self._sessionmaker() as session:
            candidate = await session.get(Candidate, candidate_id)
            if candidate is None or candidate.cv is not None:
                return
            blueprint = Blueprint.model_validate(candidate.blueprint)

            written = await self._llm.generate(
                call_type=CV_CALL,
                model=self._settings.mistral_model_cv,
                prompt=load_prompt(CV_PROMPT),
                variables=cv_variables(blueprint, sector),
                schema=CvText,
                temperature=CV_TEMPERATURE,
                max_tokens=CV_MAX_TOKENS,
                workspace_id=workspace_id,
                job_id=job_id,
                check=lambda text: not problems_in(text, blueprint),
            )

            cv = assemble(written, blueprint)
            candidate.cv = cv.model_dump(mode="json")
            candidate.cv_text = render_text(cv)
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(progress_done=Job.progress_done + 1)
            )
            await session.commit()
