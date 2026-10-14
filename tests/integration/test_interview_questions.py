"""Interview questions for the short list, end to end (PRD F8)."""

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.candidates.models import Candidate
from app.config import get_settings
from app.interview.models import QuestionSet
from app.jobs.runner import JobRunner
from app.llm.base import RATE_LIMITED, LlmError, LlmRequest
from app.llm.fake import FakeLlm, fake_interview

SignedIn = Callable[..., Awaitable[httpx.AsyncClient]]

CHOICES: dict[str, Any] = {
    "sector": "IT and software",
    "seniority": ["senior"],
    "work_mode": ["hybrid"],
    "title": "Cloud Engineer",
}
SCRIPT = [
    {"any_of": ["Microsoft Azure", "AWS"], "min_years": 3, "kind": "hard"},
    {"any_of": ["Terraform"], "min_years": 2, "kind": "hard"},
    {"any_of": ["Kubernetes"], "min_years": 0, "kind": "soft"},
]


async def with_lists(
    client: httpx.AsyncClient, runner: JobRunner, candidates: int = 20
) -> str:
    """A vacancy with candidates, a script and a short list; returns its id."""
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()
    vacancy_id: str = started["vacancy_id"]
    await client.post(f"/api/vacancies/{vacancy_id}/submit")
    await client.post(
        f"/api/vacancies/{vacancy_id}/candidates", json={"count": candidates}
    )
    await runner.wait_idle()
    await client.put(f"/api/vacancies/{vacancy_id}/script", json={"items": SCRIPT})
    await client.post(f"/api/vacancies/{vacancy_id}/screening", json={})
    await runner.wait_idle()
    return vacancy_id


async def start(
    client: httpx.AsyncClient, vacancy_id: str, **body: Any
) -> httpx.Response:
    return await client.post(f"/api/vacancies/{vacancy_id}/interview", json=body)


async def questions(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/vacancies/{vacancy_id}/interview")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def vacancy(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/vacancies/{vacancy_id}")).json()
    return body


async def test_core_and_follow_up_questions_are_made_in_the_background(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=20)
    assert (await vacancy(client, vacancy_id))["interview"] == {
        "exist": False,
        "out_of_date": False,
        "reason": None,
    }
    llm.gate = asyncio.Event()

    response = await start(client, vacancy_id)

    assert response.status_code == 202
    job = response.json()
    # 20 candidates: a short list of 2, so one core set and two follow-up sets.
    assert (job["type"], job["progress_done"], job["progress_total"]) == (
        "interview_questions",
        0,
        3,
    )
    llm.gate.set()
    await runner.wait_idle()

    done = await vacancy(client, vacancy_id)
    assert done["interview_job"]["status"] == "done"
    assert done["interview_job"]["progress_done"] == 3
    assert done["interview"]["exist"] is True
    result = await questions(client, vacancy_id)
    assert result["notice"] == "Suggestions to support a recruiter. A person decides."
    assert result["out_of_date"] is False
    core = result["core"]
    assert core["candidate_id"] is None
    # Each core question is based on a script item, shown with it.
    assert {q["source_kind"] for q in core["questions"]} == {"script_item"}
    assert core["questions"][0]["source_text"] == (
        "Microsoft Azure or AWS (required, at least 3 years)"
    )
    assert len(result["follow_ups"]) == 2


async def test_follow_ups_follow_the_short_list_and_show_the_name(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=20)
    await start(client, vacancy_id)
    await runner.wait_idle()

    result = await questions(client, vacancy_id)
    lists = (await client.get(f"/api/vacancies/{vacancy_id}/lists")).json()

    short = [(e["candidate_id"], e["name"]) for e in lists["short_list"]]
    assert [
        (f["candidate_id"], f["candidate_name"]) for f in result["follow_ups"]
    ] == short
    assert [f["list_position"] for f in result["follow_ups"]] == [1, 2]
    # Each follow-up rests on a strength or concern of that candidate.
    kinds = {q["source_kind"] for f in result["follow_ups"] for q in f["questions"]}
    assert kinds <= {"strength", "concern"}


async def test_follow_ups_rest_only_on_points_that_survived_the_evidence_check(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)

    await start(client, vacancy_id)
    await runner.wait_idle()

    follow_up = [r for r in llm.requests if r.call_type == "interview"][1:]
    lists = (await client.get(f"/api/vacancies/{vacancy_id}/lists")).json()
    entry = lists["short_list"][0]
    offered = follow_up[0].user
    for strength in entry["strengths"]:
        assert strength in offered
    for concern in entry["concerns"]:
        assert concern in offered


async def test_the_model_never_sees_a_name_or_contact_details(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)

    await start(client, vacancy_id)
    await runner.wait_idle()

    sent = "\n".join(
        r.user + json.dumps(r.variables)
        for r in llm.requests
        if r.call_type == "interview"
    )
    for person in (await db.scalars(select(Candidate))).all():
        first, last = person.name.split(" ", 1)
        for personal in (first, last, person.email, person.phone):
            assert personal not in sent


async def test_a_question_with_a_broken_link_is_dropped_and_shown_as_dropped(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)

    def inventing(request: LlmRequest) -> str:
        answer = json.loads(fake_interview(request))
        answer["questions"].append(
            {"question": "Based on nothing?", "purpose": "None.", "source": "Z9"}
        )
        return json.dumps(answer)

    llm.responders["interview"] = inventing

    await start(client, vacancy_id)
    await runner.wait_idle()

    result = await questions(client, vacancy_id)
    for question_set in [result["core"], *result["follow_ups"]]:
        assert {"kind": "source_not_found", "detail": "Z9"} in question_set["dropped"]
        assert "Based on nothing?" not in json.dumps(question_set["questions"])


async def test_a_question_about_a_protected_attribute_is_flagged_for_review(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)
    llm.script(
        "interview",
        json.dumps(
            {
                "questions": [
                    {
                        "question": "How old are you, and do you have children?",
                        "purpose": "None that is allowed.",
                        "source": "S1",
                    }
                ]
            }
        ),
    )

    await start(client, vacancy_id)
    await runner.wait_idle()

    core = (await questions(client, vacancy_id))["core"]
    assert core["questions"][0]["flags"] == ["how old (age)", "children (family)"]


async def test_questions_need_a_current_short_list(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()
    vacancy_id = started["vacancy_id"]
    await client.post(f"/api/vacancies/{vacancy_id}/submit")

    refused = await start(client, vacancy_id)

    assert refused.status_code == 409
    assert refused.json() == {
        "error": "prerequisites_missing",
        "message": "Generate the short list first.",
    }
    assert (await vacancy(client, vacancy_id))["interview"]["reason"] == (
        "Generate the short list first."
    )
    assert (
        await client.get(f"/api/vacancies/{vacancy_id}/interview")
    ).status_code == 404


async def test_changing_the_script_makes_lists_and_questions_out_of_date(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)
    await start(client, vacancy_id)
    await runner.wait_idle()

    await client.put(
        f"/api/vacancies/{vacancy_id}/script",
        json={"items": [{"any_of": ["Terraform"], "min_years": 0, "kind": "hard"}]},
    )

    state = (await vacancy(client, vacancy_id))["interview"]
    assert state["exist"] is True
    assert state["out_of_date"] is True
    assert state["reason"] == "The lists are out of date. Generate them again first."
    assert (await questions(client, vacancy_id))["out_of_date"] is True


async def test_new_lists_make_the_questions_out_of_date(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)
    await start(client, vacancy_id)
    await runner.wait_idle()

    await client.post(f"/api/vacancies/{vacancy_id}/screening", json={"replace": True})
    await runner.wait_idle()

    assert (await vacancy(client, vacancy_id))["interview"]["out_of_date"] is True


async def test_generating_again_needs_confirmation_and_replaces_the_questions(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)
    await start(client, vacancy_id)
    await runner.wait_idle()
    first = {s.id for s in (await db.scalars(select(QuestionSet))).all()}

    unconfirmed = await start(client, vacancy_id)
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["error"] == "replace_confirmation_required"

    assert (await start(client, vacancy_id, replace=True)).status_code == 202
    await runner.wait_idle()

    second = {s.id for s in (await db.scalars(select(QuestionSet))).all()}
    assert len(second) == 2  # one core set, one follow-up set for a short list of 1
    assert not first & second


async def test_edit_and_reset_a_set(signed_in: SignedIn, runner: JobRunner) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)
    await start(client, vacancy_id)
    await runner.wait_idle()
    core = (await questions(client, vacancy_id))["core"]
    base = f"/api/vacancies/{vacancy_id}/interview/{core['id']}"
    generated = core["questions"]

    edited = [
        generated[0] | {"question": "Walk me through your Azure landing zone design."},
        {"question": "What would you change in your last team?", "purpose": ""},
    ]
    saved = (await client.put(base, json={"questions": edited})).json()

    assert saved["edited"] is True
    assert [q["question"] for q in saved["questions"]] == [
        "Walk me through your Azure landing zone design.",
        "What would you change in your last team?",
    ]
    # The edited question keeps its source; the added one is the recruiter's own.
    assert saved["questions"][0]["source_text"] == generated[0]["source_text"]
    assert saved["questions"][1]["source_kind"] == "recruiter"

    reset = (await client.post(f"{base}/reset")).json()
    assert reset["edited"] is False
    assert reset["questions"] == generated


async def test_a_failed_run_can_be_retried_and_only_makes_what_is_missing(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=20)
    calls = Counter(r.call_type for r in llm.requests)["interview"]
    # The first call (core or a follow-up) fails; the others work.
    llm.script("interview", LlmError(RATE_LIMITED))

    job = (await start(client, vacancy_id)).json()
    await runner.wait_idle()

    failed = await vacancy(client, vacancy_id)
    assert failed["interview_job"]["status"] == "failed"
    assert failed["interview_job"]["error_kind"] == "llm_rate_limited"
    assert (await client.post(f"/api/jobs/{job['id']}/retry")).status_code == 202
    await runner.wait_idle()

    assert (await vacancy(client, vacancy_id))["interview_job"]["status"] == "done"
    result = await questions(client, vacancy_id)
    assert result["core"] is not None
    assert len(result["follow_ups"]) == 2
    # Three sets in total, plus the one call that failed: nothing made twice.
    assert Counter(r.call_type for r in llm.requests)["interview"] == calls + 4


async def test_runs_per_workspace_are_limited(
    signed_in: SignedIn, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_interview_runs_per_workspace", 1)
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=5)
    await start(client, vacancy_id)
    await runner.wait_idle()

    refused = await start(client, vacancy_id, replace=True)

    assert refused.status_code == 409
    assert refused.json()["message"] == (
        "This demo workspace has used all 1 interview question runs."
    )


async def test_another_workspace_cannot_make_read_or_edit_questions(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    owner = await signed_in("203.0.113.1")
    visitor = await signed_in("203.0.113.2")
    vacancy_id = await with_lists(owner, runner, candidates=5)
    await start(owner, vacancy_id)
    await runner.wait_idle()
    core = (await questions(owner, vacancy_id))["core"]
    base = f"/api/vacancies/{vacancy_id}/interview"

    responses = [
        await start(visitor, vacancy_id, replace=True),
        await visitor.get(base),
        await visitor.put(
            f"{base}/{core['id']}", json={"questions": [{"question": "X?"}]}
        ),
        await visitor.post(f"{base}/{core['id']}/reset"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404]


async def test_regenerating_candidates_removes_their_follow_ups(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=10)
    await start(client, vacancy_id)
    await runner.wait_idle()

    await client.post(
        f"/api/vacancies/{vacancy_id}/candidates", json={"count": 10, "replace": True}
    )
    await runner.wait_idle()

    # The people they were for no longer exist; the core set stays, out of date.
    remaining = (await db.scalars(select(QuestionSet))).all()
    assert [s.candidate_id for s in remaining] == [None]
    assert (await vacancy(client, vacancy_id))["interview"]["out_of_date"] is True


async def test_no_questions_or_names_reach_the_logs(
    signed_in: SignedIn,
    runner: JobRunner,
    db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = await signed_in()
    vacancy_id = await with_lists(client, runner, candidates=5)
    caplog.set_level(logging.INFO)

    await start(client, vacancy_id)
    await runner.wait_idle()

    logged = caplog.text
    assert "interview.started" in logged
    assert "interview.finished" in logged
    assert "Tell me about a time" not in logged
    for person in (await db.scalars(select(Candidate))).all():
        assert person.name.split(" ", 1)[1] not in logged
    assert await db.scalar(select(func.count()).select_from(QuestionSet)) == 2
