import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        (
            "postgresql+asyncpg://u:p@host:5432/db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ),
        # A pasted value with a trailing newline must still work.
        ("postgresql://u:p@host:5432/db\n", "postgresql+asyncpg://u:p@host:5432/db"),
    ],
)
def test_database_url_always_uses_the_async_driver(given: str, expected: str) -> None:
    assert Settings(database_url=given, _env_file=None).database_url == expected


def test_database_url_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.internal:5432/app")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+asyncpg://u:p@db.internal:5432/app"
