"""Needs the local PostgreSQL from docker-compose.yml (or DATABASE_URL)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_database_is_reachable() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()


# Not async: Alembic's env.py starts its own event loop.
def test_migrations_run_up_and_down() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
