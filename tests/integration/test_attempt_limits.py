"""Brute-force protection on the code entry endpoint (PRD F0)."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.codes import hash_ip
from app.access.models import FailedAttempt
from app.config import get_settings
from app.limits.attempts import record_failure
from tests.integration.conftest import (
    OTHER_CODE,
    UNKNOWN_CODE,
    VALID_CODE,
    AddCode,
    ClientFor,
)

LOCKED_OUT = {
    "error": "too_many_attempts",
    "message": "Too many attempts. Please wait a while and try again.",
}


async def fail(client: httpx.AsyncClient, times: int) -> None:
    for _ in range(times):
        response = await client.post("/api/session", json={"code": UNKNOWN_CODE})
        assert response.status_code == 401


async def test_an_invalid_code_counts_towards_the_attempt_limit(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await fail(client, 3)

    assert await db.scalar(select(func.count()).select_from(FailedAttempt)) == 3


async def test_ip_is_locked_out_after_ten_failures(client: httpx.AsyncClient) -> None:
    await fail(client, 10)

    response = await client.post("/api/session", json={"code": UNKNOWN_CODE})

    assert response.status_code == 429
    assert response.json() == LOCKED_OUT
    assert response.headers["retry-after"] == "900"


async def test_lockout_answer_reveals_nothing_about_codes(
    client: httpx.AsyncClient, add_code: AddCode
) -> None:
    """Valid, used-up and unknown codes all get the same answer during a lockout."""
    await add_code(VALID_CODE, label="c01")
    await add_code(OTHER_CODE, label="c02", uses=20, max_uses=20)
    await fail(client, 10)

    answers = [
        await client.post("/api/session", json={"code": code})
        for code in (VALID_CODE, OTHER_CODE, UNKNOWN_CODE)
    ]

    assert [a.status_code for a in answers] == [429, 429, 429]
    assert [a.json() for a in answers] == [LOCKED_OUT] * 3
    assert "code" not in LOCKED_OUT["message"].lower()


async def test_a_used_up_code_also_counts_as_a_failed_attempt(
    client: httpx.AsyncClient, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code(VALID_CODE, uses=20, max_uses=20)

    await client.post("/api/session", json={"code": VALID_CODE})

    assert await db.scalar(select(func.count()).select_from(FailedAttempt)) == 1


async def test_other_addresses_are_not_locked_out(
    client_for: ClientFor, add_code: AddCode
) -> None:
    await add_code(VALID_CODE)
    await fail(client_for("203.0.113.1"), 10)

    response = await client_for("203.0.113.2").post(
        "/api/session", json={"code": VALID_CODE}
    )

    assert response.status_code == 200


async def test_lockout_ends_when_the_window_has_passed(
    client: httpx.AsyncClient, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code(VALID_CODE)
    await fail(client, 10)
    assert (
        await client.post("/api/session", json={"code": VALID_CODE})
    ).status_code == 429

    long_ago = datetime.now(UTC) - timedelta(minutes=16)
    await db.execute(update(FailedAttempt).values(attempted_at=long_ago))
    await db.commit()

    response = await client.post("/api/session", json={"code": VALID_CODE})
    assert response.status_code == 200


async def test_an_existing_session_is_not_affected_by_a_lockout(
    client: httpx.AsyncClient, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code(VALID_CODE)
    await client.post("/api/session", json={"code": VALID_CODE})
    pepper = get_settings().access_code_pepper.get_secret_value()
    for _ in range(10):
        await record_failure(db, hash_ip("203.0.113.10", pepper), datetime.now(UTC))
    await db.commit()

    assert (await client.get("/api/session")).status_code == 200


async def test_global_ceiling_stops_guessing_from_many_addresses(
    client_for: ClientFor, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code(VALID_CODE)
    pepper = get_settings().access_code_pepper.get_secret_value()
    now = datetime.now(UTC)
    # 100 failures in the last hour, each from a different address.
    for n in range(100):
        await record_failure(db, hash_ip(f"192.0.2.{n}", pepper), now)
    await db.commit()

    response = await client_for("203.0.113.99").post(
        "/api/session", json={"code": VALID_CODE}
    )

    assert response.status_code == 429
    assert response.json() == LOCKED_OUT


async def test_the_submitted_code_is_not_stored_with_a_failed_attempt(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await fail(client, 1)

    row = (await db.execute(select(FailedAttempt))).scalar_one()

    assert set(FailedAttempt.__table__.columns.keys()) == {
        "id",
        "ip_hash",
        "attempted_at",
    }
    # The address is stored as a keyed hash, not in the clear.
    assert row.ip_hash != "203.0.113.10"
    assert len(row.ip_hash) == 64
