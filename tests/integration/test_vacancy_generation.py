"""Generating a vacancy in a background job (PRD F1)."""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.jobs.models import Job
from app.jobs.runner import JobRunner
from app.llm.base import RATE_LIMITED, LlmError, LlmRequest
from app.llm.fake import FakeLlm, fake_vacancy
from app.llm.usage import UsageRecord
from app.vacancy.models import Vacancy
from app.vacancy.schemas import VacancySections

SignedIn = Callable[..., Awaitable[httpx.AsyncClient]]

CHOICES: dict[str, Any] = {
    "sector": "IT and software",
    "seniority": ["senior"],
    "work_mode": ["hybrid"],
    "title": "Cloud Engineer",
    "company": "Tulip Systems",
    "emphasis": "Experience with platform teams",
}


async def start(client: httpx.AsyncClient, **changes: Any) -> dict[str, str]:
    response = await client.post("/api/vacancies", json=CHOICES | changes)
    assert response.status_code == 202, response.text
    started: dict[str, str] = response.json()
    return started


async def vacancy(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/vacancies/{vacancy_id}")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def test_generation_runs_in_the_background_and_ends_as_a_draft(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    llm.gate = asyncio.Event()

    started = await start(client)

    # The request returned at once, while the model is still "writing".
    generating = await vacancy(client, started["vacancy_id"])
    assert generating["status"] == "generating"
    assert generating["sections"] is None
    assert generating["job"]["id"] == started["job_id"]
    assert generating["job"]["status"] in ("queued", "running")

    llm.gate.set()
    await runner.wait_idle()

    ready = await vacancy(client, started["vacancy_id"])
    assert ready["status"] == "draft"
    assert ready["version"] == 1
    assert ready["flags"] == []
    assert ready["job"]["status"] == "done"
    assert ready["job"]["message"] is None
    assert (ready["job"]["progress_done"], ready["job"]["progress_total"]) == (1, 1)
    # Structured sections, not one blob.
    assert set(ready["sections"]) == {
        "title",
        "company_intro",
        "role_summary",
        "responsibilities",
        "required_qualifications",
        "nice_to_haves",
        "what_we_offer",
        "location_and_work_mode",
    }
    assert ready["sections"]["title"] == "Cloud Engineer"
    assert isinstance(ready["sections"]["responsibilities"], list)


async def test_the_model_receives_the_choices_and_the_versioned_prompt(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()

    started = await start(client)
    await runner.wait_idle()

    [request] = llm.requests
    assert request.call_type == "vacancy"
    for expected in (
        "Cloud Engineer",
        "IT and software",
        "senior",
        "hybrid",
        "Tulip Systems",
        "Experience with platform teams",
    ):
        assert expected in request.user
    stored = await db.get(Vacancy, uuid.UUID(started["vacancy_id"]))
    assert stored is not None
    assert stored.prompt_version == "vacancy_v1"
    assert stored.model == "fake"
    # The generated text is kept apart, for "Reset to generated" later.
    assert stored.generated_sections == stored.sections


async def test_each_model_call_leaves_a_usage_record(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()

    started = await start(client)
    await runner.wait_idle()

    [record] = (await db.scalars(select(UsageRecord))).all()
    assert record.call_type == "vacancy"
    assert str(record.job_id) == started["job_id"]
    assert record.workspace_id is not None
    assert record.outcome == "ok"


@pytest.mark.parametrize(
    "change",
    [
        {"seniority": []},
        {"work_mode": []},
        {"sector": "Astrology"},
        {"title": ""},
        {"title": "x" * 121},
        {"emphasis": "x" * 501},
        {"surprise": "field"},
    ],
)
async def test_invalid_choices_are_refused_on_the_server(
    change: dict[str, Any], signed_in: SignedIn, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()

    response = await client.post("/api/vacancies", json=CHOICES | change)

    assert response.status_code == 422
    assert llm.requests == []
    assert await db.scalar(select(func.count()).select_from(Vacancy)) == 0


async def test_a_model_failure_is_shown_and_can_be_retried(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    llm.script("vacancy", LlmError(RATE_LIMITED))

    started = await start(client)
    await runner.wait_idle()

    failed = await vacancy(client, started["vacancy_id"])
    assert failed["status"] == "failed"
    assert failed["job"]["status"] == "failed"
    assert failed["job"]["error_kind"] == "llm_rate_limited"
    assert failed["job"]["message"] == (
        "The model is busy right now. Please try again in a moment."
    )

    retried = await client.post(f"/api/jobs/{started['job_id']}/retry")
    assert retried.status_code == 202
    await runner.wait_idle()

    ready = await vacancy(client, started["vacancy_id"])
    assert ready["status"] == "draft"
    assert ready["job"]["status"] == "done"
    assert ready["job"]["error_kind"] is None


async def test_unusable_model_output_fails_after_one_retry(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    llm.script("vacancy", "I cannot help with that.", '{"title": "only a title"}')

    started = await start(client)
    await runner.wait_idle()

    failed = await vacancy(client, started["vacancy_id"])
    assert failed["status"] == "failed"
    assert failed["sections"] is None
    assert failed["job"]["error_kind"] == "llm_invalid_output"
    assert len(llm.requests) == 2
    outcomes = (await db.scalars(select(UsageRecord.outcome))).all()
    assert list(outcomes) == ["invalid_output", "invalid_output"]


async def test_an_unexpected_crash_fails_the_job_without_leaving_it_running(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    llm.script("vacancy", RuntimeError("boom"))

    started = await start(client)
    await runner.wait_idle()

    failed = await vacancy(client, started["vacancy_id"])
    assert failed["status"] == "failed"
    assert failed["job"]["status"] == "failed"
    assert failed["job"]["error_kind"] == "internal"
    assert failed["job"]["message"] == "Something went wrong. Please try again."


async def test_discriminatory_wording_from_the_model_is_flagged_for_review(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    answer = json.loads(fake_vacancy(llm_request()))
    answer["required_qualifications"].append("A young, native speaker of Dutch")
    llm.script("vacancy", json.dumps(answer))

    started = await start(client)
    await runner.wait_idle()

    ready = await vacancy(client, started["vacancy_id"])
    # Flagged for a person to review, not silently removed or blocked.
    assert ready["status"] == "draft"
    assert {(f["section"], f["term"]) for f in ready["flags"]} == {
        ("required_qualifications", "young"),
        ("required_qualifications", "native speaker"),
    }


def llm_request() -> LlmRequest:
    return LlmRequest(
        call_type="vacancy",
        model="fake",
        system="",
        user="",
        schema=VacancySections,
        temperature=0,
        max_tokens=1,
        variables={"title": "Cloud Engineer"},
    )


async def test_a_finished_job_cannot_be_run_again(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    started = await start(client)
    await runner.wait_idle()

    response = await client.post(f"/api/jobs/{started['job_id']}/retry")

    assert response.status_code == 409
    assert response.json()["error"] == "not_retryable"
    assert len(llm.requests) == 1


async def test_starting_the_same_job_twice_runs_it_once(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    llm.gate = asyncio.Event()
    started = await start(client)

    # As if two requests tried to start the same job.
    runner.start(uuid.UUID(started["job_id"]))
    runner.start(uuid.UUID(started["job_id"]))
    llm.gate.set()
    await runner.wait_idle()

    assert len(llm.requests) == 1


async def test_only_one_job_at_a_time_per_workspace(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    llm.gate = asyncio.Event()
    await start(client)

    second = await client.post("/api/vacancies", json=CHOICES)

    assert second.status_code == 409
    assert second.json()["error"] == "job_in_progress"
    llm.gate.set()
    await runner.wait_idle()
    assert len(llm.requests) == 1


async def test_generations_per_workspace_are_limited_and_retries_count(
    signed_in: SignedIn,
    runner: JobRunner,
    llm: FakeLlm,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "max_vacancy_generations_per_workspace", 3)
    client = await signed_in()

    await start(client)
    await runner.wait_idle()
    llm.script("vacancy", LlmError(RATE_LIMITED))
    failed = await start(client)
    await runner.wait_idle()
    # The retry is the third start.
    assert (await client.post(f"/api/jobs/{failed['job_id']}/retry")).status_code == 202
    await runner.wait_idle()

    refused = await client.post("/api/vacancies", json=CHOICES)

    assert refused.status_code == 409
    assert refused.json() == {
        "error": "limit_reached",
        "message": "This demo workspace has used all 3 vacancy generations.",
    }
    assert len(llm.requests) == 3


async def test_the_limit_of_one_workspace_does_not_affect_another(
    signed_in: SignedIn, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_vacancy_generations_per_workspace", 1)
    first = await signed_in("203.0.113.1")
    second = await signed_in("203.0.113.2")
    await start(first)
    await runner.wait_idle()

    assert (await first.post("/api/vacancies", json=CHOICES)).status_code == 409
    assert (await second.post("/api/vacancies", json=CHOICES)).status_code == 202
    await runner.wait_idle()


async def test_a_workspace_cannot_see_or_retry_anothers_work(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    owner = await signed_in("203.0.113.1")
    visitor = await signed_in("203.0.113.2")
    llm.script("vacancy", LlmError(RATE_LIMITED))
    started = await start(owner)
    await runner.wait_idle()

    assert (
        await visitor.get(f"/api/vacancies/{started['vacancy_id']}")
    ).status_code == 404
    assert (await visitor.get(f"/api/jobs/{started['job_id']}")).status_code == 404
    assert (
        await visitor.post(f"/api/jobs/{started['job_id']}/retry")
    ).status_code == 404
    assert (await visitor.get("/api/vacancies")).json() == []
    assert len((await owner.get("/api/vacancies")).json()) == 1


async def test_vacancies_are_listed_newest_first_with_their_job(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    await start(client, title="First role")
    await runner.wait_idle()
    await start(client, title="Second role")
    await runner.wait_idle()

    listed = (await client.get("/api/vacancies")).json()

    assert [v["parameters"]["title"] for v in listed] == ["Second role", "First role"]
    assert all(v["job"]["status"] == "done" for v in listed)


async def test_the_job_can_be_read_on_its_own(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    started = await start(client)
    await runner.wait_idle()

    job = (await client.get(f"/api/jobs/{started['job_id']}")).json()

    assert job["type"] == "vacancy_generation"
    assert job["status"] == "done"
    assert job["vacancy_id"] == started["vacancy_id"]


async def test_a_restart_marks_running_jobs_as_interrupted_and_they_can_be_retried(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, app: FastAPI, db: AsyncSession
) -> None:
    client = await signed_in()
    started = await start(client)
    await runner.wait_idle()
    # As if the process stopped while the job was running.
    await db.execute(update(Job).values(status="running", error_kind=None))
    await db.execute(update(Vacancy).values(status="generating", sections=None))
    await db.commit()

    # Starting the application runs the same sweep as a real restart.
    async with app.router.lifespan_context(app):
        interrupted = await vacancy(client, started["vacancy_id"])
        assert interrupted["status"] == "failed"
        assert interrupted["job"]["status"] == "interrupted"
        assert interrupted["job"]["message"] == (
            "This job was interrupted by a restart. You can run it again."
        )

        retried = await client.post(f"/api/jobs/{started['job_id']}/retry")
        assert retried.status_code == 202
        await runner.wait_idle()

        assert (await vacancy(client, started["vacancy_id"]))["status"] == "draft"


async def test_options_for_the_dialog_come_from_the_server(signed_in: SignedIn) -> None:
    client = await signed_in()

    options = (await client.get("/api/vacancy-options")).json()

    assert "IT and software" in options["sectors"]
    assert len(options["sectors"]) == 11
    assert options["seniorities"] == ["junior", "medior", "senior", "lead"]
    assert options["work_modes"] == ["office-based", "home-based", "hybrid"]
    assert options["title_max"] == 120


async def test_no_vacancy_text_reaches_the_logs(
    signed_in: SignedIn, runner: JobRunner, caplog: pytest.LogCaptureFixture
) -> None:
    client = await signed_in()
    caplog.set_level(logging.INFO)

    await start(client, emphasis="Zebra-striped onboarding ritual")
    await runner.wait_idle()

    logged = caplog.text
    # The steps are logged, with ids and counts.
    assert "vacancy.generation_started" in logged
    assert "llm.call" in logged
    assert "job.finished" in logged
    # The content is not: no choices, no generated text.
    for content in (
        "Cloud Engineer",
        "Tulip Systems",
        "Zebra-striped",
        "Fake model output",
        "Microsoft Azure",
    ):
        assert content not in logged
