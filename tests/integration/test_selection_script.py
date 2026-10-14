"""The selection script: proposal, editing, saving, out of date (PRD F5)."""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.jobs.runner import JobRunner
from app.llm.base import RATE_LIMITED, LlmError
from app.llm.fake import FakeLlm
from app.llm.usage import UsageRecord
from app.script.models import SelectionScript

SignedIn = Callable[..., Awaitable[httpx.AsyncClient]]

CHOICES: dict[str, Any] = {
    "sector": "IT and software",
    "seniority": ["senior"],
    "work_mode": ["hybrid"],
    "title": "Cloud Engineer",
}


async def submitted(client: httpx.AsyncClient, runner: JobRunner) -> str:
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()
    await client.post(f"/api/vacancies/{started['vacancy_id']}/submit")
    vacancy_id: str = started["vacancy_id"]
    return vacancy_id


async def propose(client: httpx.AsyncClient, vacancy_id: str) -> httpx.Response:
    return await client.post(f"/api/vacancies/{vacancy_id}/script/proposal")


async def script(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/vacancies/{vacancy_id}/script")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def vacancy(client: httpx.AsyncClient, vacancy_id: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/api/vacancies/{vacancy_id}")).json()
    return body


async def save(
    client: httpx.AsyncClient, vacancy_id: str, items: list[dict[str, Any]]
) -> httpx.Response:
    return await client.put(
        f"/api/vacancies/{vacancy_id}/script", json={"items": items}
    )


async def proposed_items(
    client: httpx.AsyncClient, runner: JobRunner, vacancy_id: str
) -> list[dict[str, Any]]:
    await propose(client, vacancy_id)
    await runner.wait_idle()
    items: list[dict[str, Any]] = (await script(client, vacancy_id))["proposal"][
        "items"
    ]
    return items


# --- The proposal ------------------------------------------------------------


async def test_the_model_proposes_items_in_the_background(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    assert await script(client, vacancy_id) == {"saved": None, "proposal": None}
    llm.gate = asyncio.Event()

    response = await propose(client, vacancy_id)

    assert response.status_code == 202
    assert response.json()["type"] == "script_proposal"
    running = await vacancy(client, vacancy_id)
    assert running["script_job"]["status"] in ("queued", "running")
    assert running["script"]["proposal_ready"] is False

    llm.gate.set()
    await runner.wait_idle()

    done = await vacancy(client, vacancy_id)
    assert done["script_job"]["status"] == "done"
    assert done["script"] == {
        "exists": False,
        "out_of_date": False,
        "item_count": 0,
        "proposal_ready": True,
    }
    proposal = (await script(client, vacancy_id))["proposal"]
    assert proposal["current"] is True
    first = proposal["items"][0]
    # Keywords (with alternatives), years, hard or soft, and a reason.
    assert first == {
        "any_of": ["Microsoft Azure", "AWS"],
        "min_years": 3,
        "kind": "hard",
        "reason": "Experience with Microsoft Azure",
        "grounded": True,
        "enabled": True,
    }
    assert [item["kind"] for item in proposal["items"]] == [
        "hard",
        "hard",
        "soft",
        "soft",
    ]


async def test_a_reason_that_is_not_in_the_vacancy_is_marked(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    items = await proposed_items(client, runner, vacancy_id)

    # The fake's last reason was made up; the check in code noticed.
    assert [item["grounded"] for item in items] == [True, True, True, False]
    assert items[3]["reason"] == "Agile ways of working are a plus"


async def test_the_model_reads_the_vacancy_text_and_the_call_is_recorded(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    await propose(client, vacancy_id)
    await runner.wait_idle()

    [request] = [r for r in llm.requests if r.call_type == "script"]
    assert "Experience with Microsoft Azure" in request.user
    record = (
        await db.scalars(select(UsageRecord).where(UsageRecord.call_type == "script"))
    ).one()
    assert (record.prompt_version, record.outcome) == ("script_v2", "ok")


async def test_a_proposal_is_not_a_saved_script(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    """Cancel in the dialog sends nothing, so nothing is saved."""
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    await proposed_items(client, runner, vacancy_id)

    assert (await script(client, vacancy_id))["saved"] is None
    assert await db.scalar(select(func.count()).select_from(SelectionScript)) == 0
    assert (await vacancy(client, vacancy_id))["script"]["exists"] is False


async def test_a_failed_proposal_is_shown_and_can_be_retried(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    llm.script("script", LlmError(RATE_LIMITED))

    job = (await propose(client, vacancy_id)).json()
    await runner.wait_idle()

    failed = await vacancy(client, vacancy_id)
    assert failed["script_job"]["status"] == "failed"
    assert failed["script_job"]["message"] == (
        "The model is busy right now. Please try again in a moment."
    )
    assert failed["script"]["proposal_ready"] is False

    assert (await client.post(f"/api/jobs/{job['id']}/retry")).status_code == 202
    await runner.wait_idle()
    assert (await vacancy(client, vacancy_id))["script"]["proposal_ready"] is True


async def test_unusable_model_output_fails_after_one_retry(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    llm.script("script", "no json", '{"items": []}')

    await propose(client, vacancy_id)
    await runner.wait_idle()

    failed = await vacancy(client, vacancy_id)
    assert failed["script_job"]["error_kind"] == "llm_invalid_output"
    assert Counter(r.call_type for r in llm.requests)["script"] == 2


async def test_a_script_needs_a_submitted_vacancy(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()

    proposal = await propose(client, started["vacancy_id"])
    saved = await save(
        client,
        started["vacancy_id"],
        [{"any_of": ["AWS"], "min_years": 0, "kind": "hard"}],
    )

    assert (proposal.status_code, proposal.json()["error"]) == (409, "not_submitted")
    assert (saved.status_code, saved.json()["error"]) == (409, "not_submitted")


async def test_proposals_per_workspace_are_limited(
    signed_in: SignedIn, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_script_proposals_per_workspace", 2)
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    for _ in range(2):
        assert (await propose(client, vacancy_id)).status_code == 202
        await runner.wait_idle()

    refused = await propose(client, vacancy_id)

    assert refused.status_code == 409
    assert refused.json() == {
        "error": "limit_reached",
        "message": (
            "This demo workspace has used all 2 script proposals. "
            "You can still edit and save the script by hand."
        ),
    }
    # Saving by hand still works.
    saved = await save(
        client, vacancy_id, [{"any_of": ["AWS"], "min_years": 0, "kind": "hard"}]
    )
    assert saved.status_code == 200


async def test_one_job_at_a_time_also_for_proposals(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    llm.gate = asyncio.Event()
    await propose(client, vacancy_id)

    again = await propose(client, vacancy_id)
    actions = {a["key"]: a for a in (await vacancy(client, vacancy_id))["actions"]}

    assert (again.status_code, again.json()["error"]) == (409, "job_in_progress")
    assert actions["generate_script"]["enabled"] is False
    assert actions["generate_script"]["reason"] == (
        "Wait until the running job has finished."
    )
    llm.gate.set()
    await runner.wait_idle()


# --- Editing and saving ------------------------------------------------------


async def test_the_edited_script_is_saved_with_the_vacancy_version(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    items = await proposed_items(client, runner, vacancy_id)

    # Edit the keyword and the years, flip hard to soft, remove one, add one.
    items[0]["any_of"] = ["Azure", "AWS", "GCP"]
    items[0]["min_years"] = 5
    items[1]["kind"] = "soft"
    del items[3]
    items.append({"any_of": ["Python"], "min_years": 2, "kind": "hard"})

    response = await save(client, vacancy_id, items)

    assert response.status_code == 200
    saved = response.json()["saved"]
    assert saved["revision"] == 1
    assert saved["out_of_date"] is False
    assert [(i["any_of"], i["min_years"], i["kind"]) for i in saved["items"]] == [
        (["Azure", "AWS", "GCP"], 5, "hard"),
        (["Terraform"], 2, "soft"),
        (["Kubernetes"], 0, "soft"),
        (["Python"], 2, "hard"),
    ]
    stored = (await db.scalars(select(SelectionScript))).one()
    # Linked to the version of the vacancy it was made from.
    assert stored.vacancy_version == (await vacancy(client, vacancy_id))["version"]
    assert (await vacancy(client, vacancy_id))["script"] == {
        "exists": True,
        "out_of_date": False,
        "item_count": 4,
        "proposal_ready": True,
    }


async def test_saving_again_replaces_the_script_and_raises_the_revision(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    await save(
        client, vacancy_id, [{"any_of": ["AWS"], "min_years": 0, "kind": "hard"}]
    )

    again = await save(
        client, vacancy_id, [{"any_of": ["Azure"], "min_years": 1, "kind": "soft"}]
    )

    saved = again.json()["saved"]
    assert saved["revision"] == 2
    assert [i["any_of"] for i in saved["items"]] == [["Azure"]]
    assert await db.scalar(select(func.count()).select_from(SelectionScript)) == 1


async def test_grounded_is_decided_by_the_server_not_by_the_browser(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    response = await save(
        client,
        vacancy_id,
        [
            {
                "any_of": ["AWS"],
                "min_years": 0,
                "kind": "hard",
                "reason": "The vacancy absolutely demands this",
                "grounded": True,
            },
            {
                "any_of": ["Microsoft Azure"],
                "min_years": 0,
                "kind": "hard",
                "reason": "Experience with Microsoft Azure",
                "grounded": False,
            },
        ],
    )

    assert [i["grounded"] for i in response.json()["saved"]["items"]] == [False, True]


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"any_of": [], "min_years": 0, "kind": "hard"}],
        [{"any_of": ["AWS"], "min_years": 21, "kind": "hard"}],
        [{"any_of": ["AWS"], "min_years": -1, "kind": "hard"}],
        [{"any_of": ["AWS"], "min_years": 0, "kind": "vital"}],
        [{"any_of": ["a", "b", "c", "d", "e"], "min_years": 0, "kind": "soft"}],
        [{"any_of": ["AWS"], "min_years": 0, "kind": "hard", "enabled": False}],
        [{"any_of": ["AWS"], "min_years": 0, "kind": "hard"}] * 16,
    ],
)
async def test_an_invalid_script_is_refused_on_the_server(
    items: list[dict[str, Any]],
    signed_in: SignedIn,
    runner: JobRunner,
    db: AsyncSession,
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    response = await save(client, vacancy_id, items)

    assert response.status_code == 422
    assert await db.scalar(select(func.count()).select_from(SelectionScript)) == 0


# --- Out of date -------------------------------------------------------------


async def test_editing_the_vacancy_marks_the_script_out_of_date(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    items = await proposed_items(client, runner, vacancy_id)
    await save(client, vacancy_id, items)
    current = await vacancy(client, vacancy_id)

    await client.put(
        f"/api/vacancies/{vacancy_id}/sections",
        json=current["sections"] | {"role_summary": "A different role altogether."},
    )

    # Marked, not silently reused, and still there.
    state = (await vacancy(client, vacancy_id))["script"]
    assert state["exists"] is True
    assert state["out_of_date"] is True
    assert state["item_count"] == 4
    # The old proposal no longer counts as a proposal for this text.
    assert state["proposal_ready"] is False
    both = await script(client, vacancy_id)
    assert both["saved"]["out_of_date"] is True
    assert both["proposal"]["current"] is False


async def test_saving_again_is_the_deliberate_action_that_brings_it_up_to_date(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    items = await proposed_items(client, runner, vacancy_id)
    await save(client, vacancy_id, items)
    current = await vacancy(client, vacancy_id)
    await client.put(
        f"/api/vacancies/{vacancy_id}/sections",
        json=current["sections"] | {"role_summary": "A different role altogether."},
    )

    saved = (await save(client, vacancy_id, items)).json()["saved"]

    assert saved["out_of_date"] is False
    assert saved["revision"] == 2
    assert (await vacancy(client, vacancy_id))["script"]["out_of_date"] is False


async def test_a_proposal_does_not_hide_the_state_of_a_candidate_job(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    llm.script("cv", LlmError(RATE_LIMITED))
    await client.post(f"/api/vacancies/{vacancy_id}/candidates", json={"count": 2})
    await runner.wait_idle()

    await propose(client, vacancy_id)
    await runner.wait_idle()

    both = await vacancy(client, vacancy_id)
    assert both["script_job"]["status"] == "done"
    # Still visible, with its Retry, although it is no longer the latest job.
    assert both["candidate_job"]["status"] == "failed"
    assert both["job"]["type"] == "script_proposal"


async def test_lists_say_exactly_which_prerequisite_is_missing(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)

    async def lists() -> tuple[bool, str | None]:
        actions = {a["key"]: a for a in (await vacancy(client, vacancy_id))["actions"]}
        long, short = actions["generate_long_list"], actions["generate_short_list"]
        assert (long["enabled"], long["reason"]) == (short["enabled"], short["reason"])
        return long["enabled"], long["reason"]

    assert await lists() == (False, "Generate candidates and a selection script first.")

    await save(
        client, vacancy_id, [{"any_of": ["AWS"], "min_years": 0, "kind": "hard"}]
    )
    assert await lists() == (False, "Generate candidates first.")

    await client.post(f"/api/vacancies/{vacancy_id}/candidates", json={"count": 2})
    await runner.wait_idle()
    # Both prerequisites exist and are current: the lists can be made.
    assert await lists() == (True, None)


# --- Other workspaces, deletion, logs ----------------------------------------


async def test_another_workspace_cannot_read_propose_or_save(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    owner = await signed_in("203.0.113.1")
    visitor = await signed_in("203.0.113.2")
    vacancy_id = await submitted(owner, runner)
    await save(owner, vacancy_id, [{"any_of": ["AWS"], "min_years": 0, "kind": "hard"}])

    responses = [
        await visitor.get(f"/api/vacancies/{vacancy_id}/script"),
        await propose(visitor, vacancy_id),
        await save(
            visitor, vacancy_id, [{"any_of": ["X"], "min_years": 0, "kind": "soft"}]
        ),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert (await script(owner, vacancy_id))["saved"]["items"][0]["any_of"] == ["AWS"]


async def test_no_vacancy_text_or_keywords_reach_the_logs(
    signed_in: SignedIn, runner: JobRunner, caplog: pytest.LogCaptureFixture
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    caplog.set_level(logging.INFO)

    items = await proposed_items(client, runner, vacancy_id)
    await save(client, vacancy_id, items)

    logged = caplog.text
    assert "script.proposal_started" in logged
    assert "script.saved" in logged
    for content in ("Microsoft Azure", "Terraform", "Agile ways of working"):
        assert content not in logged
