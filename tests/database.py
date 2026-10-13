"""Shared by the integration and the browser tests: the test database itself."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def _create_if_missing() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    assert url.database is not None
    assert url.database.endswith("_test"), "tests must not run on a real database"
    admin = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": url.database},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin.dispose()


def create_test_database_if_missing() -> None:
    """Create the `<name>_test` database from DATABASE_URL when it is not there.

    Runs in a thread of its own, so it also works where an event loop is
    already running (pytest-asyncio, Playwright).
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(asyncio.run, _create_if_missing()).result()
