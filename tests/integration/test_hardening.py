"""Spend cap, clean-up of idle workspaces, "Reset demo", request size (PRD 11)."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import FailedAttempt, Workspace
from app.candidates.models import Candidate
from app.config import get_settings
from app.jobs.models import Job
from app.jobs.runner import JobRunner
from app.llm.fake import FakeLlm
from app.llm.usage import UsageRecord
from app.main import clean_up_once
from app.vacancy.models import Vacancy

SignedIn = Callable[..., Awaitable[httpx.AsyncClient]]

CHOICES: dict[str, Any] = {
    "sector": "IT and software",
    "seniority": ["senior"],
    "work_mode": ["hybrid"],
    "title": "Cloud Engineer",
}
CAP_MESSAGE = (
    "The demo has reached its budget for today. Generation is switched off "
    "until midnight (UTC). Everything else keeps working."
)


async def spend(db: AsyncSession, dollars: str, when: datetime | None = None) -> None:
    """Record a model call that cost `dollars`."""
    db.add(
        UsageRecord(
            workspace_id=None,
            job_id=None,
            call_type="cv",
            model="mistral-small-2603",
            prompt_version="cv_v2",
            outcome="ok",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            estimated_cost=Decimal(dollars),
            created_at=when or datetime.now(UTC),
        )
    )
    await db.commit()


async def submitted(client: httpx.AsyncClient, runner: JobRunner) -> str:
    started = (await client.post("/api/vacancies", json=CHOICES)).json()
    await runner.wait_idle()
    await client.post(f"/api/vacancies/{started['vacancy_id']}/submit")
    vacancy_id: str = started["vacancy_id"]
    return vacancy_id


# --- Daily spend cap ---------------------------------------------------------


async def test_no_job_starts_once_the_daily_budget_is_spent(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    calls = len(llm.requests)
    await spend(db, "2.00")

    responses = [
        await client.post("/api/vacancies", json=CHOICES),
        await client.post(f"/api/vacancies/{vacancy_id}/candidates", json={"count": 5}),
        await client.post(f"/api/vacancies/{vacancy_id}/script/proposal"),
    ]

    for response in responses:
        assert response.status_code == 409
        assert response.json() == {"error": "spend_cap_reached", "message": CAP_MESSAGE}
    assert len(llm.requests) == calls
    # Everything else keeps working.
    assert (await client.get(f"/api/vacancies/{vacancy_id}")).status_code == 200


async def test_spend_from_yesterday_does_not_count(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    await spend(db, "50.00", datetime.now(UTC) - timedelta(days=1))
    await spend(db, "1.99")

    response = await client.post("/api/vacancies", json=CHOICES)

    assert response.status_code == 202
    await runner.wait_idle()


async def test_a_running_job_stops_when_the_budget_runs_out_half_way(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession, llm: FakeLlm
) -> None:
    client = await signed_in()
    vacancy_id = await submitted(client, runner)
    llm.gate = asyncio.Event()
    started = await client.post(
        f"/api/vacancies/{vacancy_id}/candidates", json={"count": 30}
    )
    assert started.status_code == 202
    # While the first calls wait, other workspaces use up the day's budget.
    await asyncio.sleep(0.05)
    await spend(db, "5.00")
    llm.gate.set()
    await runner.wait_idle()

    job = (await client.get(f"/api/vacancies/{vacancy_id}")).json()["candidate_job"]
    assert job["status"] == "failed"
    assert job["error_kind"] == "spend_cap_reached"
    assert job["message"] == CAP_MESSAGE
    # Far fewer calls than the 31 a full run would make.
    assert (
        len([r for r in llm.requests if r.call_type == "cv"])
        <= get_settings().cv_concurrency
    )


async def test_no_cap_means_no_limit(
    signed_in: SignedIn,
    runner: JobRunner,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "daily_spend_cap_usd", None)
    client = await signed_in()
    await spend(db, "1000.00")

    assert (await client.post("/api/vacancies", json=CHOICES)).status_code == 202
    await runner.wait_idle()


# --- Clean-up of idle workspaces ------------------------------------------------


async def test_idle_workspaces_are_deleted_with_all_their_data(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    idle = await signed_in("203.0.113.1")
    active = await signed_in("203.0.113.2")
    idle_vacancy = await submitted(idle, runner)
    await idle.post(f"/api/vacancies/{idle_vacancy}/candidates", json={"count": 3})
    await runner.wait_idle()
    await submitted(active, runner)
    long_ago = datetime.now(UTC) - timedelta(hours=25)
    idle_id = (
        await db.scalars(select(Vacancy.workspace_id).where(Vacancy.id == idle_vacancy))
    ).one()
    await db.execute(
        update(Workspace).where(Workspace.id == idle_id).values(last_seen_at=long_ago)
    )
    await db.commit()
    usage_before = await db.scalar(select(func.count()).select_from(UsageRecord))

    deleted = await clean_up_once()

    assert deleted == 1
    assert await db.scalar(select(func.count()).select_from(Workspace)) == 1
    assert await db.scalar(select(func.count()).select_from(Vacancy)) == 1
    assert await db.scalar(select(func.count()).select_from(Candidate)) == 0
    assert (
        await db.scalar(
            select(func.count()).select_from(Job).where(Job.workspace_id == idle_id)
        )
        == 0
    )
    # The cost was made: the usage records stay, without the link.
    assert (
        await db.scalar(select(func.count()).select_from(UsageRecord)) == usage_before
    )
    # The idle visitor's session is gone; the active one's is not.
    assert (await idle.get("/api/session")).status_code == 401
    assert (await active.get("/api/session")).status_code == 200


async def test_old_failed_attempts_are_removed(db: AsyncSession) -> None:
    now = datetime.now(UTC)
    db.add_all(
        [
            FailedAttempt(ip_hash="a" * 64, attempted_at=now - timedelta(days=2)),
            FailedAttempt(ip_hash="b" * 64, attempted_at=now - timedelta(minutes=5)),
        ]
    )
    await db.commit()

    await clean_up_once()

    remaining = (await db.scalars(select(FailedAttempt.ip_hash))).all()
    assert remaining == ["b" * 64]


async def test_the_clean_up_runs_when_the_app_starts(
    signed_in: SignedIn, app: FastAPI, db: AsyncSession
) -> None:
    client = await signed_in()
    await db.execute(
        update(Workspace).values(last_seen_at=datetime.now(UTC) - timedelta(days=3))
    )
    await db.commit()

    async with app.router.lifespan_context(app):
        await asyncio.sleep(0.2)

    assert await db.scalar(select(func.count()).select_from(Workspace)) == 0
    assert (await client.get("/api/session")).status_code == 401


# --- Reset demo -------------------------------------------------------------------


async def test_reset_demo_needs_confirmation(
    signed_in: SignedIn, runner: JobRunner, db: AsyncSession
) -> None:
    client = await signed_in()
    await submitted(client, runner)

    for body in ({}, {"confirm": False}):
        response = await client.post("/api/workspace/reset", json=body)
        assert response.status_code == 400
        assert response.json()["error"] == "confirmation_required"
    assert await db.scalar(select(func.count()).select_from(Vacancy)) == 1


async def test_reset_demo_deletes_everything_but_keeps_session_and_limits(
    signed_in: SignedIn,
    runner: JobRunner,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "max_vacancy_generations_per_workspace", 2)
    client = await signed_in()
    other = await signed_in("203.0.113.9")
    vacancy_id = await submitted(client, runner)
    await client.post(f"/api/vacancies/{vacancy_id}/candidates", json={"count": 3})
    await runner.wait_idle()
    await submitted(other, runner)

    response = await client.post("/api/workspace/reset", json={"confirm": True})

    assert response.status_code == 204
    assert (await client.get("/api/vacancies")).json() == []
    assert (await client.get("/api/session")).status_code == 200
    # Another workspace is untouched.
    assert len((await other.get("/api/vacancies")).json()) == 1
    # Limits are not reset: one generation was used, one is left.
    assert (await client.post("/api/vacancies", json=CHOICES)).status_code == 202
    await runner.wait_idle()
    refused = await client.post("/api/vacancies", json=CHOICES)
    assert refused.json()["error"] == "limit_reached"


# --- Request size --------------------------------------------------------------------


async def test_a_request_that_is_too_large_is_refused(signed_in: SignedIn) -> None:
    client = await signed_in()

    response = await client.post(
        "/api/vacancies", json=CHOICES | {"emphasis": "x" * 300_000}
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": "too_large",
        "message": "This request is too large.",
    }


async def test_a_normal_request_is_not_affected(
    signed_in: SignedIn, runner: JobRunner
) -> None:
    client = await signed_in()

    assert (await client.post("/api/vacancies", json=CHOICES)).status_code == 202
    await runner.wait_idle()
