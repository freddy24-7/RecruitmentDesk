"""Developer tooling for access codes (PRD F0)."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import admin
from app.access.codes import ALPHABET, hash_code
from app.access.models import AccessCode
from app.config import get_settings
from scripts import manage_codes
from tests.integration.conftest import VALID_CODE, AddCode

PEPPER = get_settings().access_code_pepper.get_secret_value()


async def test_create_registers_codes_with_labels_and_hashes_only(
    db: AsyncSession,
) -> None:
    created = await admin.create_codes(db, 10, PEPPER, datetime.now(UTC))
    await db.commit()

    assert [new.label for new in created] == [f"c{n:02d}" for n in range(1, 11)]
    assert len({new.code for new in created}) == 10
    for new in created:
        assert len(new.code) == 5
        assert set(new.code) <= set(ALPHABET)

    rows = (await db.scalars(select(AccessCode).order_by(AccessCode.label))).all()
    assert [row.code_hash for row in rows] == [
        hash_code(new.code, PEPPER) for new in created
    ]
    assert all(row.uses == 0 and row.max_uses == 20 for row in rows)
    # The database holds no column that could contain the code itself.
    assert "code" not in AccessCode.__table__.columns


async def test_create_continues_the_label_numbering(db: AsyncSession) -> None:
    await admin.create_codes(db, 10, PEPPER, datetime.now(UTC))
    more = await admin.create_codes(db, 2, PEPPER, datetime.now(UTC))

    assert [new.label for new in more] == ["c11", "c12"]


@pytest.mark.parametrize("count", [0, -1, 51])
async def test_create_refuses_an_unreasonable_count(
    count: int, db: AsyncSession
) -> None:
    with pytest.raises(ValueError, match="count must be between"):
        await admin.create_codes(db, count, PEPPER, datetime.now(UTC))


async def test_a_created_code_opens_the_app(
    db: AsyncSession, client: httpx.AsyncClient
) -> None:
    [new] = await admin.create_codes(db, 1, PEPPER, datetime.now(UTC))
    await db.commit()

    response = await client.post("/api/session", json={"code": new.code})

    assert response.status_code == 200


async def test_status_shows_uses_and_remaining(
    add_code: AddCode, db: AsyncSession
) -> None:
    await add_code(VALID_CODE, label="c01", uses=7, max_uses=20)

    [status] = await admin.list_status(db)

    assert (status.label, status.uses, status.max_uses, status.remaining) == (
        "c01",
        7,
        20,
        13,
    )


async def test_extend_adds_redemptions_to_a_used_up_code(
    add_code: AddCode, db: AsyncSession, client: httpx.AsyncClient
) -> None:
    await add_code(VALID_CODE, label="c03", uses=20, max_uses=20)
    refused = await client.post("/api/session", json={"code": VALID_CODE})
    assert refused.status_code == 403

    status = await admin.extend_code(db, "c03", 20)
    await db.commit()

    assert (status.max_uses, status.remaining) == (40, 20)
    accepted = await client.post("/api/session", json={"code": VALID_CODE})
    assert accepted.status_code == 200


async def test_disable_blocks_a_code_immediately(
    add_code: AddCode, db: AsyncSession, client: httpx.AsyncClient
) -> None:
    await add_code(VALID_CODE, label="c03")

    await admin.disable_code(db, "c03")
    await db.commit()

    response = await client.post("/api/session", json={"code": VALID_CODE})
    assert response.status_code == 401
    [status] = await admin.list_status(db)
    assert status.disabled
    assert status.remaining == 0


async def test_unknown_label_is_an_error(db: AsyncSession) -> None:
    with pytest.raises(admin.UnknownLabelError):
        await admin.extend_code(db, "c99", 20)
    with pytest.raises(admin.UnknownLabelError):
        await admin.disable_code(db, "c99")


# The tests below run the command-line script itself. They are not async,
# because the script starts its own event loop.


def test_cli_create_prints_each_code_once_and_writes_no_file(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert manage_codes.main(["create", "--count", "3"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert "shown only once" in lines[0]
    assert [line.split()[0] for line in lines[1:]] == ["c01", "c02", "c03"]
    assert all(len(line.split()[1]) == 5 for line in lines[1:])
    # Nothing was written to the working directory.
    assert list(tmp_path.iterdir()) == []


def test_cli_status_never_prints_codes(capsys: pytest.CaptureFixture[str]) -> None:
    manage_codes.main(["create", "--count", "3"])
    created = capsys.readouterr().out.splitlines()[1:]
    codes = [line.split()[1] for line in created]

    assert manage_codes.main(["status"]) == 0

    status = capsys.readouterr().out
    assert "c01" in status and "c03" in status
    for code in codes:
        assert code not in status


def test_cli_extend_and_disable(capsys: pytest.CaptureFixture[str]) -> None:
    manage_codes.main(["create", "--count", "1"])
    capsys.readouterr()

    assert manage_codes.main(["extend", "--label", "c01", "--uses", "5"]) == 0
    assert "limit is now 25" in capsys.readouterr().out
    assert manage_codes.main(["disable", "--label", "c01"]) == 0
    assert manage_codes.main(["status"]) == 0
    assert "disabled" in capsys.readouterr().out


def test_cli_reports_an_unknown_label(capsys: pytest.CaptureFixture[str]) -> None:
    assert manage_codes.main(["disable", "--label", "c99"]) == 1
    assert "No code with label c99" in capsys.readouterr().err


def test_cli_status_with_no_codes(capsys: pytest.CaptureFixture[str]) -> None:
    assert manage_codes.main(["status"]) == 0
    assert "No access codes exist yet" in capsys.readouterr().out
