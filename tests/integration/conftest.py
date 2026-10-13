"""Fixtures for tests that use PostgreSQL and the HTTP API."""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.codes import hash_code
from app.access.models import AccessCode
from app.config import get_settings
from app.db import get_sessionmaker
from app.jobs.runner import JobRunner
from app.llm.fake import FakeLlm
from app.main import create_app
from tests.database import create_test_database_if_missing

REPO_ROOT = Path(__file__).resolve().parents[2]

# Obviously fake codes. Real codes never appear in the repository.
VALID_CODE = "TESTA"
OTHER_CODE = "FAKEB"
UNKNOWN_CODE = "ZZZZZ"

AddCode = Callable[..., Awaitable[AccessCode]]
ClientFor = Callable[[str], httpx.AsyncClient]


def alembic_config() -> Config:
    return Config(str(REPO_ROOT / "alembic.ini"))


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create the test database once and bring it to the latest migration."""
    create_test_database_if_missing()
    command.upgrade(alembic_config(), "head")


@pytest.fixture(autouse=True)
async def clean_tables(database: None) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            text(
                "TRUNCATE usage_record, job, vacancy, workspace, failed_attempt, "
                "access_code RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def llm() -> FakeLlm:
    """The stand-in for the model. Tests script its answers and read its requests."""
    return FakeLlm()


@pytest.fixture
async def app(llm: FakeLlm) -> AsyncIterator[FastAPI]:
    app = create_app(llm_client=llm)
    yield app
    await app.state.job_runner.shutdown()


@pytest.fixture
def runner(app: FastAPI) -> JobRunner:
    runner: JobRunner = app.state.job_runner
    return runner


@pytest.fixture
async def client_for(app: FastAPI) -> AsyncIterator[ClientFor]:
    """Make a browser-like client (with its own cookies) for a given IP address."""
    clients: list[httpx.AsyncClient] = []

    def make(ip: str) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, client=(ip, 50000))
        # https, because the session cookie is marked Secure.
        client = httpx.AsyncClient(transport=transport, base_url="https://test")
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


@pytest.fixture
def client(client_for: ClientFor) -> httpx.AsyncClient:
    return client_for("203.0.113.10")


@pytest.fixture
def add_code(db: AsyncSession) -> AddCode:
    async def add(
        code: str = VALID_CODE,
        *,
        label: str = "c01",
        uses: int = 0,
        max_uses: int = 20,
        disabled: bool = False,
    ) -> AccessCode:
        pepper = get_settings().access_code_pepper.get_secret_value()
        row = AccessCode(
            label=label,
            code_hash=hash_code(code, pepper),
            uses=uses,
            max_uses=max_uses,
            disabled=disabled,
            created_at=datetime.now(UTC),
        )
        db.add(row)
        await db.commit()
        return row

    return add


@pytest.fixture
def uses_of(db: AsyncSession) -> Callable[[str], Awaitable[int]]:
    async def read(label: str) -> int:
        uses = await db.scalar(select(AccessCode.uses).where(AccessCode.label == label))
        await db.rollback()
        assert uses is not None
        return uses

    return read


@pytest.fixture
def signed_in(
    client_for: ClientFor, add_code: AddCode
) -> Callable[..., Awaitable[httpx.AsyncClient]]:
    """A client that has entered a valid code, so it has its own workspace."""
    state = {"code_added": False}

    async def sign_in(ip: str = "203.0.113.10") -> httpx.AsyncClient:
        if not state["code_added"]:
            await add_code(VALID_CODE, label="c01")
            state["code_added"] = True
        client = client_for(ip)
        response = await client.post("/api/session", json={"code": VALID_CODE})
        assert response.status_code == 200
        return client

    return sign_in
