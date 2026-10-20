import pytest
from pydantic import ValidationError

from app.config import Settings, missing_for_production


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


def production(**values: object) -> list[str]:
    complete: dict[str, object] = {
        "app_env": "production",
        "llm_provider": "mistral",
        "mistral_api_key": "fake-key-for-tests",
        "daily_spend_cap_usd": "1.00",
        "cookie_secure": True,
        "client_ip_header": "X-Real-IP",
    }
    settings = Settings(_env_file=None, **(complete | values))  # type: ignore[arg-type]
    return missing_for_production(settings)


def test_production_starts_with_all_its_protections() -> None:
    assert production() == []


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"daily_spend_cap_usd": ""}, "DAILY_SPEND_CAP_USD"),
        ({"cookie_secure": False}, "COOKIE_SECURE=true"),
        ({"client_ip_header": " "}, "CLIENT_IP_HEADER"),
        ({"mistral_api_key": ""}, "MISTRAL_API_KEY"),
    ],
)
def test_production_does_not_start_without_a_protection(
    change: dict[str, object], named: str
) -> None:
    assert production(**change) == [named]


def test_development_does_not_need_them() -> None:
    settings = Settings(
        _env_file=None, daily_spend_cap_usd="", cookie_secure=False, llm_provider="fake"
    )

    assert missing_for_production(settings) == []


def test_a_settings_error_does_not_print_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_CODE_PEPPER", "short-but-secret-value")

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)

    assert "short-but-secret-value" not in str(error.value)


def test_the_app_refuses_to_start_in_production_without_its_protections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DAILY_SPEND_CAP_USD|CLIENT_IP_HEADER"):
            create_app()
    finally:
        monkeypatch.delenv("APP_ENV")
        get_settings.cache_clear()
