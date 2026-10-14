"""The long list and the short list, end to end (PRD F6, F7)."""

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
from app.llm.base import RATE_LIMITED, LlmError, LlmRequest
from app.llm.fake import FakeLlm, fake_assessment
from app.llm.usage import UsageRecord
from app.screening.models import Assessment

SignedIn = Callable[..., Awaitable[httpx.AsyncClient]]

CHOICES: dict[str, Any] = {
    "sector": "IT and software",
    "seniority": ["senior"],
    "work_mode": ["hybrid"],
    "title": "Cloud Engineer",
}

# The fake vacancy profile plants these skills; the script screens on them.
SCRIPT = [
    {"any_of": ["Microsoft Azure", "AWS"], "min_years": 3, "kind": "hard"},
    {"any_of": ["Terraform"], "min_years": 2, "kind": "hard"},
    {"any_of": ["Kubernetes"], "min_years": 0, "kind": "soft"},
    {"any_of": ["Scrum"], "min_years": 0, "kind": "soft"},
]


async def ready(
    client: httpx.AsyncClient,
    runner: JobRunner,
    candidates: int = 20,
    script: list[dict[str, Any]] | None = None,
) -> str:
    """A submitted vacancy with candidates and a saved script; returns its id."""
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()
    vacancy_id: str = started["vacancy_id"]
    await client.post(f"/api/vacancies/{vacancy_id}/submit")
    await client.post(
        f"/api/vacancies/{vacancy_id}/candidates", json={"count": candidates}
    )
    await runner.wait_idle()
    saved = await client.put(
        f"/api/vacancies/{vacancy_id}/script", json={"items": script or SCRIPT}
    )
    assert saved.status_code == 200
    return vacancy_id


async def screen(
    client: httpx.AsyncClient, vacancy_id: str, **body: Any
) -> httpx.Response:
    return await client.post(f"/api/vacancies/{vacancy_id}/screening", json=body)


async def lists(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/vacancies/{vacancy_id}/lists")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def vacancy(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/vacancies/{vacancy_id}")).json()
    return body


async def categories(db: AsyncSession) -> dict[str, str]:
    """Candidate id to planted match category: the ground truth."""
    rows = (await db.scalars(select(Candidate))).all()
    return {str(c.id): c.blueprint["match_category"] for c in rows}


# --- The happy path ----------------------------------------------------------


async def test_one_run_produces_both_lists_in_the_background(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=20)
    assert (await vacancy(client, vacancy_id))["lists"]["exist"] is False
    assert (await client.get(f"/api/vacancies/{vacancy_id}/lists")).status_code == 404
    llm.gate = asyncio.Event()

    response = await screen(client, vacancy_id)

    assert response.status_code == 202
    job = response.json()
    assert job["type"] == "screening"
    # 20 candidates: long list 6, so the model assesses the strongest 12.
    assert (job["progress_done"], job["progress_total"]) == (0, 12)
    assert (await vacancy(client, vacancy_id))["screening_job"]["status"] in (
        "queued",
        "running",
    )

    llm.gate.set()
    await runner.wait_idle()

    done = await vacancy(client, vacancy_id)
    assert done["screening_job"]["status"] == "done"
    assert (
        done["screening_job"]["progress_done"],
        done["screening_job"]["progress_total"],
    ) == (12, 12)
    assert done["lists"] == {
        "exist": True,
        "out_of_date": False,
        "long_size": 6,
        "short_size": 2,
    }
    result = await lists(client, vacancy_id)
    assert len(result["long_list"]) == 6
    assert len(result["short_list"]) == 2
    assert result["run"]["candidates"] == 20
    assert result["run"]["assessed"] == 12
    assert result["run"]["weight_deterministic"] == 0.5
    assert result["out_of_date"] is False


@pytest.mark.parametrize(
    ("candidates", "long", "short"), [(1, 1, 1), (5, 2, 1), (10, 3, 1), (100, 10, 4)]
)
async def test_list_sizes_follow_the_number_of_candidates(
    candidates: int, long: int, short: int, signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=candidates)

    await screen(client, vacancy_id)
    await runner.wait_idle()

    result = await lists(client, vacancy_id)
    assert (len(result["long_list"]), len(result["short_list"])) == (long, short)


async def test_the_short_list_is_the_top_of_the_long_list(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=40)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    result = await lists(client, vacancy_id)

    long_ids = [entry["candidate_id"] for entry in result["long_list"]]
    short_ids = [entry["candidate_id"] for entry in result["short_list"]]
    assert short_ids == long_ids[: len(short_ids)]
    assert [entry["position"] for entry in result["long_list"]] == list(
        range(1, len(long_ids) + 1)
    )
    scores = [entry["final_score"] for entry in result["long_list"]]
    assert scores == sorted(scores, reverse=True)


async def test_each_entry_shows_contact_details_and_a_reason(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    result = await lists(client, vacancy_id)

    # Always there: a person decides.
    assert result["notice"] == "Suggestions to support a recruiter. A person decides."
    top = result["long_list"][0]
    assert top["name"]
    assert top["phone"].startswith("+44 7700 900")
    assert top["email"].endswith("@example.com")
    # The paragraph: keywords found, years of experience, and other points.
    assert top["rationale"].startswith("Found in the CV: ")
    assert "years)" in top["rationale"]
    assert "The past roles are relevant to the vacancy." in top["rationale"]
    assert top["strengths"]
    assert 0 <= top["final_score"] <= 1


async def test_the_planted_strong_matches_reach_the_short_list(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    """With the fake model, which agrees with the facts, the lists must be right."""
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=20)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    truth = await categories(db)
    result = await lists(client, vacancy_id)

    # 20 candidates have 3 planted strong matches and a short list of 2.
    assert Counter(truth.values())["strong"] == 3
    assert all(truth[e["candidate_id"]] == "strong" for e in result["short_list"])
    listed = {truth[e["candidate_id"]] for e in result["long_list"]}
    assert "weak" not in listed


async def test_the_detail_view_shows_the_evidence(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner)
    await screen(client, vacancy_id)
    await runner.wait_idle()
    top = (await lists(client, vacancy_id))["long_list"][0]

    detail = (
        await client.get(f"/api/vacancies/{vacancy_id}/lists/{top['candidate_id']}")
    ).json()

    assert detail["notice"] == "Suggestions to support a recruiter. A person decides."
    assert detail["total_years"] > 0
    # Per script item: met or not, with which keyword and how many years.
    first = detail["requirements"][0]
    assert first["keywords"] == ["Microsoft Azure", "AWS"]
    assert (first["kind"], first["min_years"], first["met"]) == ("hard", 3, True)
    assert first["keyword"] in ("Microsoft Azure", "AWS")
    assert first["years"] >= 3
    # Per keyword: the parts of the CV the claim comes from.
    evidence = {e["keyword"]: e for e in detail["evidence"]}
    snippet = evidence[first["keyword"]]["snippets"][0]
    assert snippet["where"].startswith("Job ")
    assert first["keyword"] in snippet["text"]


# --- Blind screening ---------------------------------------------------------


async def test_the_model_never_sees_a_name_or_contact_details(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    requests = [r for r in llm.requests if r.call_type == "assessment"]
    people = (await db.scalars(select(Candidate))).all()

    assert len(requests) == 6
    sent = "\n".join(r.system + r.user + json.dumps(r.variables) for r in requests)
    for person in people:
        first, last = person.name.split(" ", 1)
        for personal in (first, last, person.email, person.phone):
            assert personal not in sent
    assert "example.com" not in sent
    assert "7700" not in sent
    assert "match_category" not in sent


async def test_identifying_details_inside_a_cv_do_not_reach_the_model(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    """Broken on purpose: CVs that name their owner and give contact details."""
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=5)
    people = (await db.scalars(select(Candidate))).all()
    for person in people:
        cv = dict(person.cv or {})
        cv["profile"] = (
            f"{person.name} is an engineer. Contact {person.name.split()[0]} at "
            f"{person.email} or {person.phone}."
        )
        await db.execute(
            update(Candidate).where(Candidate.id == person.id).values(cv=cv)
        )
    await db.commit()

    await screen(client, vacancy_id)
    await runner.wait_idle()

    requests = [r for r in llm.requests if r.call_type == "assessment"]
    assert requests
    sent = "\n".join(r.user + json.dumps(r.variables) for r in requests)
    for person in people:
        first, last = person.name.split(" ", 1)
        for personal in (first, last, person.email, person.phone):
            assert personal not in sent
    assert "[removed] is an engineer." in sent


async def test_contact_details_are_joined_back_only_for_display(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    people = (await db.scalars(select(Candidate))).all()
    stored = (await db.scalars(select(Assessment))).all()

    # Nothing personal is stored with an assessment.
    assert "name" not in Assessment.__table__.columns
    blob = json.dumps(
        [
            [a.requirements, a.evidence, a.flags, a.strengths, a.rationale]
            for a in stored
        ]
    )
    for person in people:
        assert person.email not in blob
        assert person.phone not in blob
    # But the list shows them.
    entry = (await lists(client, vacancy_id))["long_list"][0]
    assert entry["email"] in {person.email for person in people}


# --- The evidence check, through the whole pipeline --------------------------


def lying(request: LlmRequest) -> str:
    """A model that claims a keyword no CV contains, and inflates every number."""
    answer = json.loads(fake_assessment(request))
    answer["found"] = [
        {"keyword": claim["keyword"], "years": claim["years"] + 9}
        for claim in answer["found"]
    ] + [{"keyword": "COBOL", "years": 12}]
    answer["strengths"].append({"text": "A COBOL veteran.", "keywords": ["COBOL"]})
    answer["reasoning"] += " Their 30 years of experience stand out."
    return json.dumps(answer)


async def test_unsupported_claims_are_removed_and_flagged(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    script = [*SCRIPT, {"any_of": ["COBOL"], "min_years": 0, "kind": "soft"}]
    vacancy_id = await ready(client, runner, candidates=5, script=script)
    llm.responders["assessment"] = lying

    await screen(client, vacancy_id)
    await runner.wait_idle()

    result = await lists(client, vacancy_id)
    for entry in result["long_list"]:
        kinds = Counter(flag["kind"] for flag in entry["flags"])
        assert kinds["keyword_not_in_cv"] == 1
        assert kinds["strength_unsupported"] == 1
        assert kinds["sentence_unsupported"] == 1
        assert kinds["years_corrected"] >= 1
        # None of it reached the text the recruiter reads.
        shown = json.dumps([entry["rationale"], entry["strengths"]])
        assert "COBOL veteran" not in shown
        assert "30 years" not in shown
        assert "Not found: " in entry["rationale"]
    # The numbers shown are the computed ones, not the model's.
    detail = (
        await client.get(
            f"/api/vacancies/{vacancy_id}/lists/{result['long_list'][0]['candidate_id']}"
        )
    ).json()
    people = {str(c.id): c for c in (await db.scalars(select(Candidate))).all()}
    planted = people[detail["candidate_id"]].blueprint["skill_years"]
    for requirement in detail["requirements"]:
        if requirement["keyword"]:
            assert requirement["years"] == planted[requirement["keyword"]]
    # Kept for the evaluation: how many claims were made, and how many held.
    made, held = (
        await db.execute(
            select(
                func.sum(Assessment.claims_made), func.sum(Assessment.claims_supported)
            )
        )
    ).one()
    assert 0 < held < made


# --- Hard requirements -------------------------------------------------------


async def test_nobody_is_listed_with_a_missed_hard_requirement_and_no_flag(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=40)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    result = await lists(client, vacancy_id)

    for entry in result["long_list"]:
        detail = (
            await client.get(
                f"/api/vacancies/{vacancy_id}/lists/{entry['candidate_id']}"
            )
        ).json()
        missed = [
            r for r in detail["requirements"] if r["kind"] == "hard" and not r["met"]
        ]
        flagged = [f for f in entry["flags"] if f["kind"] == "hard_requirement_not_met"]
        assert len(missed) == len(flagged)


async def test_too_few_qualified_candidates_are_listed_with_a_visible_flag(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    # Nobody has ten years of COBOL, so nobody meets this hard requirement.
    script = [
        {"any_of": ["COBOL"], "min_years": 10, "kind": "hard"},
        {"any_of": ["Microsoft Azure", "AWS"], "min_years": 0, "kind": "soft"},
    ]
    vacancy_id = await ready(client, runner, candidates=10, script=script)

    await screen(client, vacancy_id)
    await runner.wait_idle()

    result = await lists(client, vacancy_id)
    # The list is still filled, with the best of the rest, each flagged.
    assert len(result["long_list"]) == 3
    for entry in result["long_list"]:
        assert {
            "kind": "hard_requirement_not_met",
            "detail": "COBOL: not found in the CV",
        } in entry["flags"]


async def test_a_flag_says_how_far_short_of_the_years_a_candidate_is(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    script = [{"any_of": ["Microsoft Azure", "AWS"], "min_years": 20, "kind": "hard"}]
    vacancy_id = await ready(client, runner, candidates=10, script=script)

    await screen(client, vacancy_id)
    await runner.wait_idle()

    details = [
        flag["detail"]
        for entry in (await lists(client, vacancy_id))["long_list"]
        for flag in entry["flags"]
    ]
    assert any(" years of " in detail and "20 asked" in detail for detail in details)


async def test_a_model_that_loves_everyone_cannot_override_a_hard_requirement(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    """Broken on purpose: the model gives every candidate 100."""
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=20)

    def adoring(request: LlmRequest) -> str:
        answer = json.loads(fake_assessment(request))
        answer["fit_score"] = 100
        return json.dumps(answer)

    llm.responders["assessment"] = adoring

    await screen(client, vacancy_id)
    await runner.wait_idle()

    listed = {e["candidate_id"] for e in (await lists(client, vacancy_id))["long_list"]}
    rows = (await db.scalars(select(Assessment))).all()
    by_candidate = {str(row.candidate_id): row for row in rows}
    for candidate_id in listed:
        row = by_candidate[candidate_id]
        assert row.meets_hard or any(
            flag["kind"] == "hard_requirement_not_met" for flag in row.flags
        )
    # Candidates who qualify are never passed over for one who does not.
    qualified = [r for r in rows if r.meets_hard and r.llm_score is not None]
    unqualified_listed = [
        by_candidate[c] for c in listed if not by_candidate[c].meets_hard
    ]
    if unqualified_listed:
        assert all(str(r.candidate_id) in listed for r in qualified)


# --- Prerequisites, replacing, out of date -----------------------------------


async def test_lists_need_candidates_and_a_script(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()
    vacancy_id = started["vacancy_id"]
    await client.post(f"/api/vacancies/{vacancy_id}/submit")

    neither = await screen(client, vacancy_id)
    await client.put(f"/api/vacancies/{vacancy_id}/script", json={"items": SCRIPT})
    no_candidates = await screen(client, vacancy_id)

    assert neither.status_code == 409
    assert neither.json() == {
        "error": "prerequisites_missing",
        "message": "Generate candidates and a selection script first.",
    }
    assert no_candidates.json()["message"] == "Generate candidates first."


async def test_out_of_date_inputs_are_not_silently_used(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=5)
    current = await vacancy(client, vacancy_id)
    await client.put(
        f"/api/vacancies/{vacancy_id}/sections",
        json=current["sections"] | {"role_summary": "A different role altogether."},
    )

    refused = await screen(client, vacancy_id)
    actions = {a["key"]: a for a in (await vacancy(client, vacancy_id))["actions"]}

    assert refused.status_code == 409
    assert refused.json()["message"] == (
        "The candidates are out of date. Generate candidates again first."
    )
    assert actions["generate_long_list"]["enabled"] is False
    assert actions["generate_short_list"]["reason"] == (
        "The candidates are out of date. Generate candidates again first."
    )


async def test_generating_again_needs_confirmation_and_replaces_the_lists(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    await screen(client, vacancy_id)
    await runner.wait_idle()
    first_run = (await vacancy(client, vacancy_id))["screening_job"]["id"]

    unconfirmed = await screen(client, vacancy_id)

    assert unconfirmed.status_code == 409
    assert unconfirmed.json() == {
        "error": "replace_confirmation_required",
        "message": (
            "This vacancy already has a long list and a short list. "
            "Generating again replaces them."
        ),
    }

    confirmed = await screen(client, vacancy_id, replace=True)
    await runner.wait_idle()

    assert confirmed.status_code == 202
    runs = set((await db.scalars(select(Assessment.run_id))).all())
    assert len(runs) == 1
    assert str(next(iter(runs))) != first_run
    assert await db.scalar(select(func.count()).select_from(Assessment)) == 10


async def test_changing_the_script_marks_the_lists_out_of_date(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    await client.put(
        f"/api/vacancies/{vacancy_id}/script",
        json={"items": [{"any_of": ["Terraform"], "min_years": 0, "kind": "hard"}]},
    )

    # Marked, not thrown away and not silently kept as if still valid.
    assert (await vacancy(client, vacancy_id))["lists"]["out_of_date"] is True
    result = await lists(client, vacancy_id)
    assert result["out_of_date"] is True
    assert len(result["long_list"]) == 3


async def test_editing_the_vacancy_marks_the_lists_out_of_date(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    await screen(client, vacancy_id)
    await runner.wait_idle()
    current = await vacancy(client, vacancy_id)

    await client.put(
        f"/api/vacancies/{vacancy_id}/sections",
        json=current["sections"] | {"role_summary": "A different role altogether."},
    )

    assert (await vacancy(client, vacancy_id))["lists"] == {
        "exist": True,
        "out_of_date": True,
        "long_size": 3,
        "short_size": 1,
    }


async def test_regenerating_candidates_removes_the_lists_made_from_the_old_ones(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    await client.post(
        f"/api/vacancies/{vacancy_id}/candidates", json={"count": 10, "replace": True}
    )
    await runner.wait_idle()

    # The people on those lists no longer exist.
    assert (await vacancy(client, vacancy_id))["lists"]["exist"] is False
    assert (await client.get(f"/api/vacancies/{vacancy_id}/lists")).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Assessment)) == 0


# --- Failures, limits, logs --------------------------------------------------


async def test_a_failed_run_shows_no_half_finished_lists_and_can_be_retried(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    llm.script("assessment", LlmError(RATE_LIMITED))

    job = (await screen(client, vacancy_id)).json()
    await runner.wait_idle()

    failed = await vacancy(client, vacancy_id)
    assert failed["screening_job"]["status"] == "failed"
    assert failed["screening_job"]["error_kind"] == "llm_rate_limited"
    assert failed["lists"]["exist"] is False
    calls = Counter(r.call_type for r in llm.requests)["assessment"]

    assert (await client.post(f"/api/jobs/{job['id']}/retry")).status_code == 202
    await runner.wait_idle()

    done = await vacancy(client, vacancy_id)
    assert done["screening_job"]["status"] == "done"
    assert done["lists"]["exist"] is True
    # Idempotent: the retry only asked for the assessments still missing.
    total = Counter(r.call_type for r in llm.requests)["assessment"]
    assert total <= calls + 6


async def test_unusable_model_output_is_retried_once_per_candidate(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=5)
    llm.script("assessment", "no json", '{"fit_score": 200}')

    await screen(client, vacancy_id)
    await runner.wait_idle()

    outcomes = (
        await db.scalars(
            select(UsageRecord.outcome).where(UsageRecord.call_type == "assessment")
        )
    ).all()
    assert Counter(outcomes)["invalid_output"] == 2
    # Each of the four assessed candidates still got a usable answer.
    assert Counter(outcomes)["ok"] == 4
    assert (await vacancy(client, vacancy_id))["lists"]["exist"] is True


async def test_screening_runs_per_workspace_are_limited(
    signed_in: SignedIn, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_screening_runs_per_workspace", 1)
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=5)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    refused = await screen(client, vacancy_id, replace=True)

    assert refused.status_code == 409
    assert refused.json()["message"] == (
        "This demo workspace has used all 1 screening runs."
    )


async def test_each_run_records_how_it_was_made(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    await screen(client, vacancy_id)
    await runner.wait_idle()

    job = (await db.scalars(select(Job).where(Job.type == "screening"))).one()

    assert job.result == {
        "vacancy_version": 1,
        "script_revision": 1,
        "candidates": 10,
        "assessed": 6,
        "long_size": 3,
        "short_size": 1,
        "weight_deterministic": 0.5,
        "model": "fake",
        "prompt_version": "assessment_v2",
    }


async def test_another_workspace_cannot_screen_or_read_the_lists(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    owner = await signed_in("203.0.113.1")
    visitor = await signed_in("203.0.113.2")
    vacancy_id = await ready(owner, runner, candidates=5)
    await screen(owner, vacancy_id)
    await runner.wait_idle()
    listed = (await lists(owner, vacancy_id))["long_list"][0]["candidate_id"]

    responses = [
        await screen(visitor, vacancy_id, replace=True),
        await visitor.get(f"/api/vacancies/{vacancy_id}/lists"),
        await visitor.get(f"/api/vacancies/{vacancy_id}/lists/{listed}"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]


async def test_a_candidate_who_is_not_on_a_list_has_no_entry(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=10)
    await screen(client, vacancy_id)
    await runner.wait_idle()
    unlisted = await db.scalar(
        select(Assessment.candidate_id).where(Assessment.in_long_list.is_(False))
    )

    response = await client.get(f"/api/vacancies/{vacancy_id}/lists/{unlisted}")

    assert response.status_code == 404


async def test_no_cv_text_names_or_reasons_reach_the_logs(
    signed_in: SignedIn,
    runner: JobRunner,
    db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = await signed_in()
    vacancy_id = await ready(client, runner, candidates=5)
    caplog.set_level(logging.INFO)

    await screen(client, vacancy_id)
    await runner.wait_idle()

    logged = caplog.text
    assert "screening.started" in logged
    assert "screening.finished" in logged
    for person in (await db.scalars(select(Candidate))).all():
        first, last = person.name.split(" ", 1)
        for personal in (first, last, person.email, person.phone):
            assert personal not in logged
    for content in (
        "Found in the CV",
        "The past roles are relevant",
        "Microsoft Azure",
    ):
        assert content not in logged
