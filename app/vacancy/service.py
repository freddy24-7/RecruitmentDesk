"""Generating a vacancy: start the job, do the work, retry (PRD F1)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.jobs.models import QUEUED, RETRYABLE, Job
from app.jobs.runner import JobFailed
from app.limits.workspace import VACANCY_GENERATION, check_can_generate_vacancy
from app.llm.base import LlmError
from app.llm.prompts import load_prompt
from app.llm.service import LlmService
from app.vacancy.guardrails import find_flags
from app.vacancy.models import DRAFT, FAILED, GENERATING, Vacancy
from app.vacancy.schemas import VacancyParameters, VacancySections

PROMPT_VERSION = "vacancy_v1"
CALL_TYPE = "vacancy"
# Some variety in wording is welcome for a job advert. Assessments, later,
# use a low temperature.
TEMPERATURE = 0.7
MAX_TOKENS = 2000


async def start_generation(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    parameters: VacancyParameters,
    settings: Settings,
) -> tuple[Vacancy, Job]:
    """Create the vacancy and its job. The caller commits and starts the job."""
    await check_can_generate_vacancy(session, workspace_id, settings)
    now = datetime.now(UTC)
    vacancy = Vacancy(
        workspace_id=workspace_id,
        status=GENERATING,
        parameters=parameters.model_dump(mode="json"),
        created_at=now,
        updated_at=now,
    )
    session.add(vacancy)
    await session.flush()
    job = Job(
        workspace_id=workspace_id,
        type=VACANCY_GENERATION,
        vacancy_id=vacancy.id,
        created_at=now,
    )
    session.add(job)
    await session.flush()
    return vacancy, job


async def retry_generation(session: AsyncSession, job: Job, settings: Settings) -> bool:
    """Queue a failed or interrupted job again. False if it was not retryable."""
    await check_can_generate_vacancy(session, job.workspace_id, settings)
    # Conditional, so a double click queues the job once.
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
    if queued is None:
        return False
    if job.vacancy_id is not None:
        await session.execute(
            update(Vacancy)
            .where(Vacancy.id == job.vacancy_id, Vacancy.status == FAILED)
            .values(status=GENERATING, updated_at=datetime.now(UTC))
        )
    return True


def prompt_variables(parameters: VacancyParameters) -> dict[str, str]:
    return {
        "title": parameters.title,
        "sector": parameters.sector.value,
        "seniority": ", ".join(level.value for level in parameters.seniority),
        "work_mode": ", ".join(mode.value for mode in parameters.work_mode),
        "company": parameters.company or "",
        "emphasis": parameters.emphasis or "",
    }


class VacancyGenerator:
    """The handler for `vacancy_generation` jobs."""

    def __init__(self, llm: LlmService, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    async def __call__(self, session: AsyncSession, job: Job) -> None:
        vacancy = await session.scalar(
            select(Vacancy).where(Vacancy.id == job.vacancy_id)
        )
        if vacancy is None:
            # The vacancy was deleted while the job waited: nothing to do.
            return
        vacancy_id = vacancy.id
        try:
            await self._generate(vacancy, job)
        except Exception as error:
            # Whatever went wrong, the vacancy must not stay "generating".
            await session.rollback()
            await session.execute(
                update(Vacancy)
                .where(Vacancy.id == vacancy_id, Vacancy.status == GENERATING)
                .values(status=FAILED, updated_at=datetime.now(UTC))
            )
            await session.commit()
            if isinstance(error, LlmError):
                raise JobFailed(error.kind) from error
            raise

    async def _generate(self, vacancy: Vacancy, job: Job) -> None:
        parameters = VacancyParameters.model_validate(vacancy.parameters)
        prompt = load_prompt(PROMPT_VERSION)
        model = self._settings.mistral_model_vacancy

        sections = await self._llm.generate(
            call_type=CALL_TYPE,
            model=model,
            prompt=prompt,
            variables=prompt_variables(parameters),
            schema=VacancySections,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            workspace_id=vacancy.workspace_id,
            job_id=job.id,
        )

        # Idempotent: running the job again simply replaces the generated text.
        as_json = sections.model_dump(mode="json")
        vacancy.sections = as_json
        vacancy.generated_sections = as_json
        vacancy.flags = [flag.model_dump() for flag in find_flags(sections)]
        vacancy.version = 1
        vacancy.prompt_version = prompt.version
        vacancy.model = self._llm.model_name(model)
        vacancy.status = DRAFT
        vacancy.updated_at = datetime.now(UTC)
        job.progress_done = 1


async def fail_generating_vacancies(session: AsyncSession) -> None:
    """At startup, together with mark_interrupted_jobs: no job is running any more."""
    await session.execute(
        update(Vacancy)
        .where(Vacancy.status == GENERATING)
        .values(status=FAILED, updated_at=datetime.now(UTC))
    )
