"""No submitted code appears in the logs (PRD F0, CLAUDE.md rule 15)."""

import logging

import httpx
import pytest

from tests.integration.conftest import OTHER_CODE, VALID_CODE, AddCode

# A wrong guess that is easy to search for in the log output.
WRONG_GUESS = "QQQQQ"


async def test_submitted_codes_never_reach_the_logs(
    client: httpx.AsyncClient, add_code: AddCode, caplog: pytest.LogCaptureFixture
) -> None:
    await add_code(VALID_CODE, label="c01")
    await add_code(OTHER_CODE, label="c02", uses=20, max_uses=20)
    # Everything, including the SQL statements and their parameters.
    caplog.set_level(logging.DEBUG)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
    try:
        await client.post("/api/session", json={"code": WRONG_GUESS})
        await client.post("/api/session", json={"code": "qqqqq"})
        await client.post("/api/session", json={"code": OTHER_CODE})
        await client.post("/api/session", json={"code": VALID_CODE})
    finally:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.NOTSET)

    logged = caplog.text

    # The test is only meaningful if these requests were actually logged.
    assert "access.code_rejected" in logged
    assert "access.session_started" in logged
    assert "UPDATE access_code" in logged
    for code in (WRONG_GUESS, "qqqqq", OTHER_CODE, VALID_CODE):
        assert code not in logged
    # The label is logged instead, so usage can still be followed.
    assert "c01" in logged
