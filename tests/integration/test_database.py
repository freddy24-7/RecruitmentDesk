"""Needs the local PostgreSQL from docker-compose.yml (or DATABASE_URL)."""

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import alembic_config


async def test_database_is_reachable(db: AsyncSession) -> None:
    assert await db.scalar(text("SELECT 1")) == 1


async def test_tests_run_on_a_test_database(db: AsyncSession) -> None:
    name = await db.scalar(text("SELECT current_database()"))

    assert name is not None
    assert name.endswith("_test")


# Not async: Alembic's env.py starts its own event loop.
def test_migrations_run_up_and_down() -> None:
    config = alembic_config()

    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_migrations_match_the_models() -> None:
    """Fails if a model changed without a migration for it."""
    command.check(alembic_config())
