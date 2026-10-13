"""Review, edit, reset, cancel and submit a vacancy (PRD F2, F3)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.jobs.models import Job
from app.jobs.runner import JobRunner
from app.llm.base import RATE_LIMITED, LlmError
from app.llm.fake import FakeLlm
from app.llm.usage import UsageRecord
from app.vacancy.models import Vacancy

SignedIn = Callable[..., Awaitable[httpx.AsyncClient]]

CHOICES: dict[str, Any] = {
    "sector": "IT and software",
    "seniority": ["senior"],
    "work_mode": ["hybrid"],
    "title": "Cloud Engineer",
}


async def draft(client: httpx.AsyncClient, runner: JobRunner) -> dict[str, Any]:
    """Generate a vacancy and return it as a finished draft."""
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()
    body: dict[str, Any] = (
        await client.get(f"/api/vacancies/{started['vacancy_id']}")
    ).json()
    assert body["status"] == "draft"
    return body


async def save(
    client: httpx.AsyncClient, vacancy: dict[str, Any], **changes: Any
) -> httpx.Response:
    return await client.put(
        f"/api/vacancies/{vacancy['id']}/sections", json=vacancy["sections"] | changes
    )


# --- Edit and reset ---------------------------------------------------------


async def test_an_edit_is_saved_as_a_new_version(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    assert (vacancy["version"], vacancy["edited"]) == (1, False)

    response = await save(
        client,
        vacancy,
        role_summary="  You lead the platform team.  ",
        responsibilities=["Lead the team", "", "  Review designs  "],
    )

    assert response.status_code == 200
    edited = response.json()
    assert edited["version"] == 2
    assert edited["edited"] is True
    assert edited["status"] == "draft"
    # Text is tidied on the way in.
    assert edited["sections"]["role_summary"] == "You lead the platform team."
    assert edited["sections"]["responsibilities"] == ["Lead the team", "Review designs"]


async def test_saving_without_changes_does_not_make_a_new_version(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)

    response = await save(client, vacancy)

    assert response.json()["version"] == 1


async def test_a_draft_can_be_saved_with_an_empty_section(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)

    response = await save(client, vacancy, responsibilities=[], role_summary="")

    assert response.status_code == 200
    assert response.json()["sections"]["responsibilities"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"role_summary": "x" * 3001},
        {"responsibilities": ["x"] * 16},
        {"responsibilities": ["x" * 401]},
        {"responsibilities": "not a list"},
        {"extra_section": "text"},
    ],
)
async def test_edits_are_validated_on_the_server(
    change: dict[str, Any], signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)

    response = await save(client, vacancy, **change)

    assert response.status_code == 422
    assert (await client.get(f"/api/vacancies/{vacancy['id']}")).json()["version"] == 1


async def test_a_missing_section_in_an_edit_is_refused(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    incomplete = {k: v for k, v in vacancy["sections"].items() if k != "what_we_offer"}

    response = await client.put(
        f"/api/vacancies/{vacancy['id']}/sections", json=incomplete
    )

    assert response.status_code == 422


async def test_reset_brings_back_the_generated_text(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    await save(client, vacancy, role_summary="My own words.")

    response = await client.post(f"/api/vacancies/{vacancy['id']}/reset")

    assert response.status_code == 200
    reset = response.json()
    assert reset["sections"] == vacancy["sections"]
    assert reset["edited"] is False
    # The reset is itself a new version: 1 generated, 2 edited, 3 reset.
    assert reset["version"] == 3


async def test_flags_follow_the_edited_text(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    assert vacancy["flags"] == []

    flagged = (
        await save(client, vacancy, required_qualifications=["A young team player"])
    ).json()
    cleared = (
        await save(client, flagged, required_qualifications=["A team player"])
    ).json()

    assert [(f["section"], f["term"]) for f in flagged["flags"]] == [
        ("required_qualifications", "young")
    ]
    assert cleared["flags"] == []


async def test_a_vacancy_that_is_being_written_cannot_be_edited(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    llm.gate = asyncio.Event()
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    sections = {
        "title": "x",
        "company_intro": "x",
        "role_summary": "x",
        "responsibilities": ["x"],
        "required_qualifications": ["x"],
        "nice_to_haves": [],
        "what_we_offer": ["x"],
        "location_and_work_mode": "x",
    }

    edit = await client.put(
        f"/api/vacancies/{started['vacancy_id']}/sections", json=sections
    )
    reset = await client.post(f"/api/vacancies/{started['vacancy_id']}/reset")

    assert (edit.status_code, edit.json()["error"]) == (409, "not_editable")
    assert reset.status_code == 409
    llm.gate.set()
    await runner.wait_idle()


# --- Submit -----------------------------------------------------------------


async def test_submit_moves_a_draft_to_the_submitted_vacancies(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    assert vacancy["submitted_at"] is None
    assert vacancy["actions"] == []

    response = await client.post(f"/api/vacancies/{vacancy['id']}/submit")

    assert response.status_code == 200
    submitted = response.json()
    assert submitted["status"] == "submitted"
    assert submitted["submitted_at"] is not None
    [listed] = (await client.get("/api/vacancies")).json()
    assert listed["status"] == "submitted"


async def test_submit_refuses_empty_required_sections_and_names_them(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    await save(client, vacancy, responsibilities=[], what_we_offer=[], role_summary="")

    response = await client.post(f"/api/vacancies/{vacancy['id']}/submit")

    assert response.status_code == 422
    assert response.json() == {
        "error": "sections_incomplete",
        "message": (
            "These sections are still empty: The role, Responsibilities, What we offer."
        ),
    }
    assert (await client.get(f"/api/vacancies/{vacancy['id']}")).json()[
        "status"
    ] == "draft"


async def test_nice_to_haves_may_be_empty_on_submit(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    await save(client, vacancy, nice_to_haves=[])

    response = await client.post(f"/api/vacancies/{vacancy['id']}/submit")

    assert response.status_code == 200


async def test_a_vacancy_cannot_be_submitted_twice(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    await client.post(f"/api/vacancies/{vacancy['id']}/submit")

    again = await client.post(f"/api/vacancies/{vacancy['id']}/submit")

    assert (again.status_code, again.json()["error"]) == (409, "not_a_draft")


async def test_a_submitted_vacancy_can_be_edited_but_must_stay_complete(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    await client.post(f"/api/vacancies/{vacancy['id']}/submit")

    edited = await save(client, vacancy, role_summary="Sharper wording.")
    emptied = await save(client, vacancy, responsibilities=[])

    assert edited.status_code == 200
    assert edited.json()["status"] == "submitted"
    assert edited.json()["version"] == 2
    assert emptied.status_code == 422
    assert emptied.json()["message"] == (
        "These sections are still empty: Responsibilities."
    )


async def test_submitted_vacancy_lists_its_actions_with_reasons(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)

    submitted = (await client.post(f"/api/vacancies/{vacancy['id']}/submit")).json()

    actions = {action["key"]: action for action in submitted["actions"]}
    assert list(actions) == [
        "edit",
        "generate_candidates",
        "generate_script",
        "generate_long_list",
        "generate_short_list",
    ]
    assert actions["edit"]["enabled"] is True
    assert actions["edit"]["reason"] is None
    assert actions["generate_candidates"]["enabled"] is True
    assert actions["generate_script"]["enabled"] is True
    # Visible but disabled, each with the reason: nothing to make a list from.
    for key in ("generate_long_list", "generate_short_list"):
        assert actions[key]["enabled"] is False
        assert actions[key]["reason"] == (
            "Generate candidates and a selection script first."
        )
    assert actions["generate_short_list"]["label"] == "Generate short-list"


# --- Cancel -----------------------------------------------------------------


async def test_cancel_without_the_confirmation_flag_is_refused(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)

    missing = await client.delete(f"/api/vacancies/{vacancy['id']}")
    denied = await client.delete(f"/api/vacancies/{vacancy['id']}?confirm=false")

    for response in (missing, denied):
        assert response.status_code == 400
        assert response.json()["error"] == "confirmation_required"
    assert await db.scalar(select(func.count()).select_from(Vacancy)) == 1


async def test_cancel_deletes_the_vacancy_and_leaves_no_content_behind(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    await save(client, vacancy, role_summary="Zebra-striped onboarding ritual")

    response = await client.delete(f"/api/vacancies/{vacancy['id']}?confirm=true")

    assert response.status_code == 204
    assert (await client.get(f"/api/vacancies/{vacancy['id']}")).status_code == 404
    assert (await client.get("/api/vacancies")).json() == []
    assert await db.scalar(select(func.count()).select_from(Vacancy)) == 0

    # Search every text and JSON column of every table for the content.
    columns = (
        await db.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name <> 'alembic_version' "
                "AND data_type IN ('character varying', 'text', 'json', 'jsonb')"
            )
        )
    ).all()
    assert len(columns) > 5
    for table, column in columns:
        for content in ("Zebra-striped", "Cloud Engineer", "Fake model output"):
            found = await db.scalar(
                text(
                    f'SELECT count(*) FROM "{table}" '
                    f'WHERE "{column}"::text LIKE :pattern'
                ),
                {"pattern": f"%{content}%"},
            )
            assert found == 0, f"{content!r} is still in {table}.{column}"


async def test_cancel_keeps_only_the_accounting_rows_without_a_link(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)

    await client.delete(f"/api/vacancies/{vacancy['id']}?confirm=true")

    # The job still counts towards the limit, but no longer points anywhere.
    [job] = (await db.scalars(select(Job))).all()
    assert job.vacancy_id is None
    # The cost was made, so the usage record stays.
    assert await db.scalar(select(func.count()).select_from(UsageRecord)) == 1


async def test_cancelling_does_not_give_the_generation_budget_back(
    signed_in: SignedIn, runner: JobRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_vacancy_generations_per_workspace", 1)
    client = await signed_in()
    vacancy = await draft(client, runner)
    await client.delete(f"/api/vacancies/{vacancy['id']}?confirm=true")

    again = await client.post("/api/vacancies", json=CHOICES)

    assert (again.status_code, again.json()["error"]) == (409, "limit_reached")


async def test_a_failed_vacancy_can_be_cancelled(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    llm.script("vacancy", LlmError(RATE_LIMITED))
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()

    response = await client.delete(
        f"/api/vacancies/{started['vacancy_id']}?confirm=true"
    )

    assert response.status_code == 204


async def test_a_vacancy_that_is_being_written_cannot_be_cancelled(
    signed_in: SignedIn, runner: JobRunner, llm: FakeLlm
) -> None:
    client = await signed_in()
    llm.gate = asyncio.Event()
    started = (await client.post("/api/vacancies", json=CHOICES)).json()

    response = await client.delete(
        f"/api/vacancies/{started['vacancy_id']}?confirm=true"
    )

    assert (response.status_code, response.json()["error"]) == (409, "not_cancellable")
    llm.gate.set()
    await runner.wait_idle()


async def test_a_submitted_vacancy_cannot_be_cancelled(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()
    vacancy = await draft(client, runner)
    await client.post(f"/api/vacancies/{vacancy['id']}/submit")

    response = await client.delete(f"/api/vacancies/{vacancy['id']}?confirm=true")

    assert response.status_code == 409


# --- Other workspaces -------------------------------------------------------


async def test_another_workspace_cannot_edit_reset_submit_or_cancel(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    owner = await signed_in("203.0.113.1")
    visitor = await signed_in("203.0.113.2")
    vacancy = await draft(owner, runner)
    base = f"/api/vacancies/{vacancy['id']}"

    responses = [
        await visitor.put(f"{base}/sections", json=vacancy["sections"]),
        await visitor.post(f"{base}/reset"),
        await visitor.post(f"{base}/submit"),
        await visitor.delete(f"{base}?confirm=true"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404, 404]
    unchanged = (await owner.get(base)).json()
    assert (unchanged["status"], unchanged["version"]) == ("draft", 1)
