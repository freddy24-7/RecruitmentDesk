"""Browser tests: the real frontend and the real backend, with the fake model.

    npm --prefix web run build
    uv run playwright install chromium     # once
    uv run pytest -m e2e tests/e2e

The backend runs as a separate process and serves the built frontend, as it
will in production. It uses the test database and never the real model.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.access.codes import hash_code
from app.access.models import AccessCode
from tests.database import create_test_database_if_missing

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "web" / "dist"

# An obviously fake code. Real codes never appear in the repository.
E2E_CODE = "TESTA"
# Long enough to see the spinner, short enough to keep the tests quick.
FAKE_DELAY_SECONDS = "1.0"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


async def _reset_database() -> None:
    """Empty every table and register one access code."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as session:
            await session.execute(
                text(
                    "TRUNCATE assessment, selection_script, candidate, "
                    "usage_record, job, "
                    "vacancy, workspace, "
                    "failed_attempt, "
                    "access_code RESTART IDENTITY CASCADE"
                )
            )
            session.add(
                AccessCode(
                    label="c01",
                    code_hash=hash_code(E2E_CODE, os.environ["ACCESS_CODE_PEPPER"]),
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def server() -> Iterator[str]:
    """Start the application and return its address."""
    if not (FRONTEND / "index.html").is_file():
        pytest.fail("Build the frontend first: npm --prefix web run build")
    assert os.environ["DATABASE_URL"].endswith("_test")

    env = os.environ | {
        "FRONTEND_DIST": str(FRONTEND),
        "LLM_PROVIDER": "fake",
        "FAKE_LLM_DELAY_SECONDS": FAKE_DELAY_SECONDS,
    }
    # This job may be the first to use the test database (as in CI).
    create_test_database_if_missing()
    migration = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if migration.returncode != 0:
        pytest.fail(f"Migrations failed:\n{migration.stderr[-2000:]}")

    port = _free_port()
    address = f"http://localhost:{port}"
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                if httpx.get(f"{address}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None or time.monotonic() > deadline:
                pytest.fail("The application did not start")
            time.sleep(0.2)
        yield address
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def app_url(server: str) -> str:
    """The address of the application, with an empty database and one code."""
    # In a thread of its own: Playwright already runs an event loop in this one.
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, _reset_database()).result()
    return server
