import pytest
from pydantic import ValidationError

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


@pytest.mark.parametrize("name", ["ACCESS_CODE_PEPPER", "SESSION_SECRET"])
def test_the_app_does_not_start_without_its_secrets(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(name)

    with pytest.raises(ValidationError, match=name.lower()):
        Settings(_env_file=None)


@pytest.mark.parametrize("name", ["ACCESS_CODE_PEPPER", "SESSION_SECRET"])
def test_short_secrets_are_refused(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(name, "too-short")

    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(_env_file=None)


def test_secrets_are_not_shown_when_settings_are_printed() -> None:
    settings = Settings(_env_file=None)

    assert settings.access_code_pepper.get_secret_value() not in repr(settings)
    assert settings.session_secret.get_secret_value() not in repr(settings)


def test_an_empty_contact_url_means_no_contact_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTACT_URL", "  ")

    assert Settings(_env_file=None).contact_url is None
