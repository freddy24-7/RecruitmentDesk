"""The acceptance criteria of the access gate (PRD F0)."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import AccessCode, Workspace
from app.access.sessions import COOKIE_NAME
from tests.integration.conftest import (
    OTHER_CODE,
    UNKNOWN_CODE,
    VALID_CODE,
    AddCode,
    ClientFor,
)

UsesOf = Callable[[str], Awaitable[int]]


async def test_valid_code_starts_a_session_and_counts_one_use(
    client: httpx.AsyncClient, add_code: AddCode, uses_of: UsesOf, db: AsyncSession
) -> None:
    await add_code(VALID_CODE, label="c01")

    response = await client.post("/api/session", json={"code": VALID_CODE})

    assert response.status_code == 200
    assert await uses_of("c01") == 1
    assert (await client.get("/api/session")).status_code == 200
    # The workspace records which code created it.
    code_label = await db.scalar(
        select(AccessCode.label).join(
            Workspace, Workspace.access_code_id == AccessCode.id
        )
    )
    assert code_label == "c01"


async def test_session_cookie_is_httponly_secure_and_lax(
    client: httpx.AsyncClient, add_code: AddCode
) -> None:
    await add_code()

    response = await client.post("/api/session", json={"code": VALID_CODE})

    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(f"{COOKIE_NAME}=")
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


async def test_reloading_or_returning_does_not_count_another_use(
    client: httpx.AsyncClient, add_code: AddCode, uses_of: UsesOf, db: AsyncSession
) -> None:
    await add_code(VALID_CODE, label="c01")
    await client.post("/api/session", json={"code": VALID_CODE})

    for _ in range(3):
        assert (await client.get("/api/session")).status_code == 200
    # Even entering the code again while the session is valid costs nothing.
    again = await client.post("/api/session", json={"code": VALID_CODE})

    assert again.status_code == 200
    assert await uses_of("c01") == 1
    assert await db.scalar(select(func.count()).select_from(Workspace)) == 1


async def test_the_21st_redemption_is_refused_as_used_up(
    client_for: ClientFor, add_code: AddCode, uses_of: UsesOf
) -> None:
    await add_code(VALID_CODE, label="c01", max_uses=20)

    for visitor in range(20):
        response = await client_for(f"198.51.100.{visitor}").post(
            "/api/session", json={"code": VALID_CODE}
        )
        assert response.status_code == 200

    refused = await client_for("198.51.100.200").post(
        "/api/session", json={"code": VALID_CODE}
    )

    assert refused.status_code == 403
    assert refused.json() == {
        "error": "code_exhausted",
        "message": (
            "This access code has been used the maximum number of times. "
            "Please contact the developer to get a new code."
        ),
        "contact_url": "https://example.com/contact",
    }
    assert COOKIE_NAME not in refused.cookies
    assert await uses_of("c01") == 20


async def test_25_simultaneous_redemptions_with_one_use_left_give_one_success(
    client_for: ClientFor, add_code: AddCode, uses_of: UsesOf, db: AsyncSession
) -> None:
    await add_code(VALID_CODE, label="c01", uses=19, max_uses=20)
    # A different address each, so the attempt limit plays no part here.
    clients = [client_for(f"198.51.100.{n}") for n in range(25)]

    responses = await asyncio.gather(
        *(c.post("/api/session", json={"code": VALID_CODE}) for c in clients)
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200] + [403] * 24
    assert await uses_of("c01") == 20
    assert await db.scalar(select(func.count()).select_from(Workspace)) == 1


@pytest.mark.parametrize("typed", ["testa", "  TESTA  ", "\tTestA\n"])
async def test_lowercase_or_space_padded_code_works(
    typed: str, client: httpx.AsyncClient, add_code: AddCode
) -> None:
    await add_code(VALID_CODE)

    response = await client.post("/api/session", json={"code": typed})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "typed", [UNKNOWN_CODE, "", "TEST", "TESTAA", "TEST1", "TESTO"]
)
async def test_invalid_code_gives_the_not_valid_message(
    typed: str, client: httpx.AsyncClient, add_code: AddCode, uses_of: UsesOf
) -> None:
    await add_code(VALID_CODE, label="c01")

    response = await client.post("/api/session", json={"code": typed})

    assert response.status_code == 401
    assert response.json() == {
        "error": "invalid_code",
        "message": "That code is not valid. Check the code and try again.",
    }
    assert COOKIE_NAME not in response.cookies
    assert await uses_of("c01") == 0


async def test_disabled_code_is_reported_as_not_valid(
    client: httpx.AsyncClient, add_code: AddCode
) -> None:
    await add_code(VALID_CODE, disabled=True)

    response = await client.post("/api/session", json={"code": VALID_CODE})

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_code"


async def test_codes_are_counted_separately(
    client_for: ClientFor, add_code: AddCode, uses_of: UsesOf
) -> None:
    await add_code(VALID_CODE, label="c01")
    await add_code(OTHER_CODE, label="c02")

    await client_for("198.51.100.1").post("/api/session", json={"code": OTHER_CODE})

    assert await uses_of("c01") == 0
    assert await uses_of("c02") == 1


async def test_without_a_session_the_api_answers_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/session")

    assert response.status_code == 401
    assert response.json()["error"] == "no_session"


@pytest.mark.parametrize("cookie", ["", "garbage", "abc.def", "ImZha2UiLg.signature"])
async def test_a_forged_cookie_is_not_a_session(
    cookie: str, client: httpx.AsyncClient
) -> None:
    client.cookies.set(COOKIE_NAME, cookie)

    assert (await client.get("/api/session")).status_code == 401


async def test_session_ends_after_24_hours_of_inactivity(
    client: httpx.AsyncClient, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code()
    await client.post("/api/session", json={"code": VALID_CODE})

    idle_since = datetime.now(UTC) - timedelta(hours=24, minutes=1)
    await db.execute(update(Workspace).values(last_seen_at=idle_since))
    await db.commit()

    assert (await client.get("/api/session")).status_code == 401


async def test_activity_keeps_the_session_alive(
    client: httpx.AsyncClient, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code()
    await client.post("/api/session", json={"code": VALID_CODE})
    almost_expired = datetime.now(UTC) - timedelta(hours=23)
    await db.execute(update(Workspace).values(last_seen_at=almost_expired))
    await db.commit()

    response = await client.get("/api/session")

    assert response.status_code == 200
    # The idle deadline moved forward, and the cookie was renewed with it.
    last_seen = await db.scalar(select(Workspace.last_seen_at))
    assert last_seen is not None
    assert datetime.now(UTC) - last_seen < timedelta(minutes=1)
    assert COOKIE_NAME in response.headers.get("set-cookie", "")


async def test_a_cookie_for_a_deleted_workspace_is_not_a_session(
    client: httpx.AsyncClient, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code()
    await client.post("/api/session", json={"code": VALID_CODE})

    await db.execute(delete(Workspace))
    await db.commit()

    assert (await client.get("/api/session")).status_code == 401


# --- Per-IP limit on new sessions ---------------------------------------------


async def test_one_address_may_start_five_sessions_per_hour(
    client_for: ClientFor, add_code: AddCode, uses_of: UsesOf, db: AsyncSession
) -> None:
    await add_code(VALID_CODE, label="c01")
    # A fresh client each time: a new visitor, without a session cookie.
    started = [
        await client_for("203.0.113.50").post("/api/session", json={"code": VALID_CODE})
        for _ in range(5)
    ]

    refused = await client_for("203.0.113.50").post(
        "/api/session", json={"code": VALID_CODE}
    )
    elsewhere = await client_for("203.0.113.51").post(
        "/api/session", json={"code": VALID_CODE}
    )

    assert [r.status_code for r in started] == [200] * 5
    assert refused.status_code == 429
    assert refused.json()["error"] == "too_many_sessions"
    assert refused.headers["Retry-After"] == "3600"
    assert COOKIE_NAME not in refused.cookies
    assert elsewhere.status_code == 200
    # The refused request did not use up a redemption.
    assert await uses_of("c01") == 6
    # Only a keyed hash of the address is stored.
    hashes = (await db.scalars(select(Workspace.ip_hash))).all()
    assert all(h and "203.0.113" not in h for h in hashes)


async def test_sessions_older_than_an_hour_do_not_count(
    client_for: ClientFor, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code(VALID_CODE, label="c01")
    for _ in range(5):
        await client_for("203.0.113.50").post("/api/session", json={"code": VALID_CODE})
    await db.execute(
        update(Workspace).values(created_at=datetime.now(UTC) - timedelta(minutes=61))
    )
    await db.commit()

    again = await client_for("203.0.113.50").post(
        "/api/session", json={"code": VALID_CODE}
    )

    assert again.status_code == 200


async def test_simultaneous_requests_from_one_address_cannot_pass_the_limit(
    client_for: ClientFor, add_code: AddCode, db: AsyncSession
) -> None:
    await add_code(VALID_CODE, label="c01")
    clients = [client_for("203.0.113.50") for _ in range(12)]

    responses = await asyncio.gather(
        *(c.post("/api/session", json={"code": VALID_CODE}) for c in clients)
    )

    assert sorted(r.status_code for r in responses) == [200] * 5 + [429] * 7
    assert await db.scalar(select(func.count()).select_from(Workspace)) == 5


async def test_a_spoofed_address_header_does_not_get_around_the_lockout(
    client_for: ClientFor, add_code: AddCode
) -> None:
    # Locally CLIENT_IP_HEADER is not set, so the header must be ignored.
    client = client_for("203.0.113.60")
    for n in range(10):
        await client.post(
            "/api/session",
            json={"code": UNKNOWN_CODE},
            headers={"X-Real-IP": f"198.51.100.{n}", "X-Forwarded-For": f"192.0.2.{n}"},
        )

    refused = await client.post(
        "/api/session",
        json={"code": UNKNOWN_CODE},
        headers={"X-Real-IP": "198.51.100.99"},
    )

    assert refused.status_code == 429
