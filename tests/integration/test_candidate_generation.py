"""Generating candidates in a background job (PRD F4)."""

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.candidates.models import Candidate
from app.config import get_settings
from app.jobs.models import Job
from app.jobs.runner import JobRunner
from app.llm.base import RATE_LIMITED, LlmError, LlmRequest, LlmResponse
from app.llm.fake import FakeLlm, fake_cv
from app.llm.usage import UsageRecord
from app.vacancy.models import Vacancy

SignedIn = Callable[..., Awaitable[httpx.AsyncClient]]

CHOICES: dict[str, Any] = {
    "sector": "IT and software",
    "seniority": ["senior"],
    "work_mode": ["hybrid"],
    "title": "Cloud Engineer",
}


async def submitted(client: httpx.AsyncClient, runner: JobRunner) -> str:
    """Generate and submit a vacancy; return its id."""
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()
    response = await client.post(f"/api/vacancies/{started['vacancy_id']}/submit")
    assert response.status_code == 200
    vacancy_id: str = started["vacancy_id"]
    return vacancy_id


async def generate(
    client: httpx.AsyncClient, vacancy_id: str, count: int, **extra: Any
) -> httpx.Response:
    return await client.post(
        f"/api/vacancies/{vacancy_id}/candidates", json={"count": count} | extra
    )


async def listed(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/vacancies/{vacancy_id}/candidates")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def vacancy(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/vacancies/{vacancy_id}")).json()
    return body


# --- The happy path -----------------------------------------------------------


async def test_candidates_are_generated_in_the_background_with_progress(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    llm.gate = asyncio.Event()

    response = await generate(client, vacancy_id, 8)

    # The request returned at once, with a job that counts "x of N".
    assert response.status_code == 202
    job = response.json()
    assert job["type"] == "candidate_generation"
    assert (job["progress_done"], job["progress_total"]) == (0, 8)
    running = await vacancy(client, vacancy_id)
    assert running["job"]["status"] in ("queued", "running")
    assert running["candidates"] == {"count": 0, "out_of_date": False}

    llm.gate.set()
    await runner.wait_idle()

    done = await vacancy(client, vacancy_id)
    assert done["job"]["status"] == "done"
    assert (done["job"]["progress_done"], done["job"]["progress_total"]) == (8, 8)
    assert done["candidates"] == {"count": 8, "out_of_date": False}
    assert len((await listed(client, vacancy_id))["candidates"]) == 8


async def test_a_candidate_has_fictional_contact_details_and_a_structured_cv(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 5)
    await runner.wait_idle()

    page = await listed(client, vacancy_id)
    assert page["vacancy_title"] == "Cloud Engineer"
    summary = page["candidates"][0]
    assert summary["number"] == 1
    assert summary["email"].endswith("@example.com")
    assert summary["phone"].startswith("+44 7700 900")
    assert summary["years_experience"] > 0
    assert summary["current_title"]

    detail = (
        await client.get(f"/api/vacancies/{vacancy_id}/candidates/{summary['id']}")
    ).json()
    cv = detail["cv"]
    # Structured: employment history with dates, education, skills, languages
    # and a short profile.
    assert set(cv) == {"profile", "positions", "education", "skills", "languages"}
    assert cv["profile"]
    assert all(
        {"title", "company", "start", "end", "highlights", "skills"} <= set(p)
        for p in cv["positions"]
    )
    assert cv["positions"][0]["start"] <= "2026-12"
    assert cv["education"][0]["year"] > 1990
    assert {language["language"] for language in cv["languages"]} >= {
        "Dutch",
        "English",
    }


async def test_the_cv_contains_no_name_contact_details_or_protected_attributes(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 20)
    await runner.wait_idle()

    candidates = (await db.scalars(select(Candidate))).all()

    assert len(candidates) == 20
    for candidate in candidates:
        text = (candidate.cv_text or "") + json.dumps(candidate.cv)
        first, last = candidate.name.split(" ", 1)
        for personal in (first, last, candidate.email, candidate.phone, "example.com"):
            assert personal not in text
        lowered = text.lower()
        for forbidden in (
            "date of birth",
            "born in",
            "years old",
            "gender",
            "marital",
            "nationality",
            "photo",
        ):
            assert forbidden not in lowered


async def test_the_model_writes_each_cv_without_knowing_who_it_is_for(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 10)
    await runner.wait_idle()

    cv_requests = [r for r in llm.requests if r.call_type == "cv"]
    names = (await db.scalars(select(Candidate.name))).all()

    assert len(cv_requests) == 10
    sent = "\n".join(r.system + r.user + json.dumps(r.variables) for r in cv_requests)
    for name in names:
        first, last = name.split(" ", 1)
        assert first not in sent
        assert last not in sent
    assert "example.com" not in sent
    assert "7700" not in sent
    # The ground truth is not sent either.
    assert "match_category" not in sent
    for category in ("strong", "partial", "adjacent", "weak"):
        assert f'"{category}"' not in sent


async def test_blueprints_are_kept_as_ground_truth_but_never_served(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 20)
    await runner.wait_idle()

    stored = (await db.scalars(select(Candidate).order_by(Candidate.number))).all()
    categories = Counter(c.blueprint["match_category"] for c in stored)
    assert categories == {"strong": 3, "partial": 7, "adjacent": 6, "weak": 4}

    page = await listed(client, vacancy_id)
    detail = (
        await client.get(
            f"/api/vacancies/{vacancy_id}/candidates/{page['candidates'][0]['id']}"
        )
    ).json()
    served = json.dumps([page, detail, await vacancy(client, vacancy_id)])
    assert "match_category" not in served
    assert "blueprint" not in served
    assert "avoid_skills" not in served
    assert "skill_years" not in served


async def test_one_profile_call_and_one_call_per_cv_are_recorded(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    job = (await generate(client, vacancy_id, 6)).json()
    await runner.wait_idle()

    records = (
        await db.scalars(select(UsageRecord).where(UsageRecord.job_id == job["id"]))
    ).all()

    assert Counter(r.call_type for r in records) == {"vacancy_profile": 1, "cv": 6}
    assert {r.prompt_version for r in records} == {"vacancy_profile_v2", "cv_v2"}


async def test_the_same_vacancy_text_is_not_analysed_twice(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 2)
    await runner.wait_idle()

    await generate(client, vacancy_id, 2, replace=True)
    await runner.wait_idle()

    assert Counter(r.call_type for r in llm.requests)["vacancy_profile"] == 1


async def test_cvs_are_written_with_limited_concurrency(
    signed_in: SignedIn, runner: JobRunner, app: Any
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    class Counting(FakeLlm):
        def __init__(self) -> None:
            super().__init__()
            self.running = 0
            self.most_at_once = 0

        async def complete(self, request: LlmRequest) -> LlmResponse:
            self.running += 1
            self.most_at_once = max(self.most_at_once, self.running)
            try:
                await asyncio.sleep(0.01)
                return await super().complete(request)
            finally:
                self.running -= 1

    counting = Counting()
    app.state.llm.client = counting

    await generate(client, vacancy_id, 30)
    await runner.wait_idle()

    assert len((await listed(client, vacancy_id))["candidates"]) == 30
    # Really side by side, but never more than the configured number.
    assert 1 < counting.most_at_once <= get_settings().cv_concurrency


# --- The cap ------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, -1, 101, 1000])
async def test_the_number_of_candidates_is_capped_on_the_server(
    count: int, signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    calls_before = len(llm.requests)

    response = await generate(client, vacancy_id, count)

    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_count",
        "message": "Choose a number from 1 to 100.",
    }
    assert len(llm.requests) == calls_before
    assert await db.scalar(select(func.count()).select_from(Candidate)) == 0


@pytest.mark.parametrize("count", ["ten", 2.5, None])
async def test_a_count_that_is_not_a_whole_number_is_refused(
    count: Any, signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    assert (await generate(client, vacancy_id, count)).status_code == 422


@pytest.mark.parametrize("count", [1, 100])
async def test_the_smallest_and_largest_pool_work(
    count: int, signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    assert (await generate(client, vacancy_id, count)).status_code == 202
    await runner.wait_idle()

    assert len((await listed(client, vacancy_id))["candidates"]) == count


async def test_candidates_need_a_submitted_vacancy(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()

    response = await generate(client, started["vacancy_id"], 5)

    assert (response.status_code, response.json()["error"]) == (409, "not_submitted")


async def test_a_workspace_has_a_total_candidate_budget(
    signed_in: SignedIn, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_candidates_per_workspace", 10)
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 7)
    await runner.wait_idle()

    too_many = await generate(client, vacancy_id, 4, replace=True)
    fits = await generate(client, vacancy_id, 3, replace=True)

    assert too_many.status_code == 409
    assert too_many.json() == {
        "error": "limit_reached",
        "message": (
            "This demo workspace can generate 10 candidates in total. "
            "There is room for 3 more."
        ),
    }
    assert fits.status_code == 202
    await runner.wait_idle()


async def test_only_one_job_runs_at_a_time(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    llm.gate = asyncio.Event()
    await generate(client, vacancy_id, 3)

    again = await generate(client, vacancy_id, 3, replace=True)
    actions = {a["key"]: a for a in (await vacancy(client, vacancy_id))["actions"]}

    assert (again.status_code, again.json()["error"]) == (409, "job_in_progress")
    # The action is shown as disabled, with the reason.
    assert actions["generate_candidates"]["enabled"] is False
    assert actions["generate_candidates"]["reason"] == (
        "Wait until the running job has finished."
    )
    llm.gate.set()
    await runner.wait_idle()


# --- Regenerating ---------------------------------------------------------------


async def test_regenerating_needs_confirmation_and_replaces_the_candidates(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 6)
    await runner.wait_idle()
    before = {c["name"] for c in (await listed(client, vacancy_id))["candidates"]}

    unconfirmed = await generate(client, vacancy_id, 4)

    assert unconfirmed.status_code == 409
    assert unconfirmed.json() == {
        "error": "replace_confirmation_required",
        "message": (
            "This vacancy already has 6 candidates. Generating again replaces them."
        ),
    }
    assert {
        c["name"] for c in (await listed(client, vacancy_id))["candidates"]
    } == before

    confirmed = await generate(client, vacancy_id, 4, replace=True)
    await runner.wait_idle()

    assert confirmed.status_code == 202
    after = {c["name"] for c in (await listed(client, vacancy_id))["candidates"]}
    assert len(after) == 4
    # A new run has a new seed: other people, and none of the old rows remain.
    assert not after & before
    assert await db.scalar(select(func.count()).select_from(Candidate)) == 4


async def test_each_run_stores_its_seed_so_the_pool_can_be_reproduced(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 3)
    await runner.wait_idle()
    await generate(client, vacancy_id, 3, replace=True)
    await runner.wait_idle()

    params = (
        await db.scalars(
            select(Job.params)
            .where(Job.type == "candidate_generation")
            .order_by(Job.created_at)
        )
    ).all()

    assert params == [
        {"count": 3, "seed": 20261013},
        {"count": 3, "seed": 20261014},
    ]


async def test_editing_the_vacancy_marks_the_candidates_out_of_date(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 4)
    await runner.wait_idle()
    current = await vacancy(client, vacancy_id)
    assert current["candidates"]["out_of_date"] is False

    edited = current["sections"] | {"role_summary": "A different role altogether."}
    await client.put(f"/api/vacancies/{vacancy_id}/sections", json=edited)

    # Marked, not silently reused, and still there.
    assert (await vacancy(client, vacancy_id))["candidates"] == {
        "count": 4,
        "out_of_date": True,
    }
    page = await listed(client, vacancy_id)
    assert page["out_of_date"] is True
    assert len(page["candidates"]) == 4

    # Regenerating is the deliberate action that clears it, and it reads the
    # new text: the vacancy is analysed again.
    await generate(client, vacancy_id, 4, replace=True)
    await runner.wait_idle()
    assert (await vacancy(client, vacancy_id))["candidates"]["out_of_date"] is False
    assert Counter(r.call_type for r in llm.requests)["vacancy_profile"] == 2


# --- Failures -------------------------------------------------------------------


async def test_a_bad_cv_is_retried_once_and_the_rest_carries_on(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    # The first CV answer is unusable; the retry gets a normal answer.
    llm.script("cv", "not json at all")

    await generate(client, vacancy_id, 5)
    await runner.wait_idle()

    done = await vacancy(client, vacancy_id)
    assert done["job"]["status"] == "done"
    assert done["candidates"]["count"] == 5
    assert Counter(r.call_type for r in llm.requests)["cv"] == 6


async def test_a_cv_with_personal_details_is_rejected_as_invalid_output(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    def with_birth_date(request: LlmRequest) -> str:
        answer = json.loads(fake_cv(request))
        answer["profile"] = "Born in 1988. Married with two children."
        return json.dumps(answer)

    llm.responders["cv"] = with_birth_date

    await generate(client, vacancy_id, 2)
    await runner.wait_idle()

    failed = await vacancy(client, vacancy_id)
    assert failed["job"]["status"] == "failed"
    assert failed["job"]["error_kind"] == "llm_invalid_output"
    assert failed["candidates"]["count"] == 0
    # Nothing with those details was stored.
    assert (await db.scalars(select(Candidate.cv_text))).all() == [None, None]


async def test_failed_cvs_do_not_block_the_others_and_retry_only_writes_the_missing(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    # One candidate gets unusable answers, on the first try and on the retry
    # of that call: that CV fails. The fault is "repaired" further down.
    broken: dict[str, Any] = {"candidate": None, "repaired": False}

    def sometimes_bad(request: LlmRequest) -> str:
        who = (
            request.variables["positions_json"] + request.variables["years_experience"]
        )
        if broken["candidate"] is None:
            broken["candidate"] = who
        if who == broken["candidate"] and not broken["repaired"]:
            return "not json at all"
        return fake_cv(request)

    llm.responders["cv"] = sometimes_bad

    job = (await generate(client, vacancy_id, 6)).json()
    await runner.wait_idle()

    partly = await vacancy(client, vacancy_id)
    assert partly["job"]["status"] == "failed"
    assert (partly["job"]["progress_done"], partly["job"]["progress_total"]) == (5, 6)
    assert partly["candidates"]["count"] == 5
    assert len((await listed(client, vacancy_id))["candidates"]) == 5
    calls = len(llm.requests)
    broken["repaired"] = True

    retried = await client.post(f"/api/jobs/{job['id']}/retry")
    await runner.wait_idle()

    assert retried.status_code == 202
    done = await vacancy(client, vacancy_id)
    assert done["job"]["status"] == "done"
    assert (done["job"]["progress_done"], done["job"]["progress_total"]) == (6, 6)
    assert done["candidates"]["count"] == 6
    # Idempotent: one more call, for the one missing CV. The other five kept.
    assert len(llm.requests) == calls + 1


async def test_when_the_model_is_unreachable_the_job_stops_early(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    calls_before = len(llm.requests)
    llm.script("cv", *[LlmError(RATE_LIMITED)] * 50)

    await generate(client, vacancy_id, 50)
    await runner.wait_idle()

    failed = await vacancy(client, vacancy_id)
    assert failed["job"]["status"] == "failed"
    assert failed["job"]["error_kind"] == "llm_rate_limited"
    assert failed["job"]["message"] == (
        "The model is busy right now. Please try again in a moment."
    )
    # Not 50 hopeless calls: it gave up after the ones already under way.
    cv_calls = len(llm.requests) - calls_before - 1
    assert cv_calls <= get_settings().cv_concurrency


async def test_a_failed_profile_call_fails_the_job_before_anything_is_replaced(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await generate(client, vacancy_id, 3)
    await runner.wait_idle()
    current = await vacancy(client, vacancy_id)
    await client.put(
        f"/api/vacancies/{vacancy_id}/sections",
        json=current["sections"] | {"role_summary": "Changed."},
    )
    llm.script("vacancy_profile", LlmError(RATE_LIMITED))

    await generate(client, vacancy_id, 3, replace=True)
    await runner.wait_idle()

    failed = await vacancy(client, vacancy_id)
    assert failed["job"]["status"] == "failed"
    # The old candidates are still there.
    assert failed["candidates"]["count"] == 3


async def test_a_job_cannot_be_retried_for_ever(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    llm.script("cv", *[LlmError(RATE_LIMITED)] * 10)
    job = (await generate(client, vacancy_id, 1)).json()
    await runner.wait_idle()

    first = await client.post(f"/api/jobs/{job['id']}/retry")
    await runner.wait_idle()
    second = await client.post(f"/api/jobs/{job['id']}/retry")
    await runner.wait_idle()
    third = await client.post(f"/api/jobs/{job['id']}/retry")

    assert (first.status_code, second.status_code) == (202, 202)
    assert third.status_code == 409
    assert third.json()["message"] == (
        "This job was already tried 3 times. Start a new one instead."
    )


async def test_an_interrupted_run_can_be_finished(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, app: Any, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    job = (await generate(client, vacancy_id, 5)).json()
    await runner.wait_idle()
    # As if the process stopped when three of the five CVs were written.
    await db.execute(
        update(Candidate).where(Candidate.number > 3).values(cv=None, cv_text=None)
    )
    await db.execute(update(Job).where(Job.id == job["id"]).values(status="running"))
    await db.commit()
    calls = len(llm.requests)

    async with app.router.lifespan_context(app):
        interrupted = await vacancy(client, vacancy_id)
        assert interrupted["job"]["status"] == "interrupted"
        assert interrupted["candidates"]["count"] == 3
        # A submitted vacancy is not damaged by the restart.
        assert interrupted["status"] == "submitted"

        await client.post(f"/api/jobs/{job['id']}/retry")
        await runner.wait_idle()

    assert (await vacancy(client, vacancy_id))["candidates"]["count"] == 5
    assert len(llm.requests) == calls + 2


# --- Other workspaces, logs ---------------------------------------------------------


async def test_another_workspace_cannot_generate_or_read_candidates(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    owner = await signed_in("203.0.113.1")
    visitor = await signed_in("203.0.113.2")
    vacancy_id = await submitted(owner, runner)
    await generate(owner, vacancy_id, 2)
    await runner.wait_idle()
    candidate_id = (await listed(owner, vacancy_id))["candidates"][0]["id"]
    base = f"/api/vacancies/{vacancy_id}/candidates"

    responses = [
        await visitor.post(base, json={"count": 2, "replace": True}),
        await visitor.get(base),
        await visitor.get(f"{base}/{candidate_id}"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert len((await listed(owner, vacancy_id))["candidates"]) == 2


async def test_a_candidate_of_another_vacancy_is_not_found(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    first = await submitted(client, runner)
    second = await submitted(client, runner)
    await generate(client, first, 1)
    await runner.wait_idle()
    candidate_id = (await listed(client, first))["candidates"][0]["id"]

    response = await client.get(f"/api/vacancies/{second}/candidates/{candidate_id}")

    assert response.status_code == 404
    assert await db.scalar(select(func.count()).select_from(Vacancy)) == 2


async def test_no_cv_text_or_personal_data_reaches_the_logs(
    signed_in: SignedIn,
    runner: JobRunner,
    db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    caplog.set_level(logging.INFO)

    await generate(client, vacancy_id, 5)
    await runner.wait_idle()

    logged = caplog.text
    assert "candidates.generation_started" in logged
    assert "candidates.generated" in logged
    candidates = (await db.scalars(select(Candidate))).all()
    for candidate in candidates:
        first, last = candidate.name.split(" ", 1)
        for personal in (first, last, candidate.email, candidate.phone):
            assert personal not in logged
        assert candidate.cv is not None
        for position in candidate.cv["positions"]:
            assert position["company"] not in logged
            assert all(h not in logged for h in position["highlights"])
    assert "Fake model output" not in logged
