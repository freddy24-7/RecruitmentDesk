"""Application settings, read from the environment (and `.env` in development)."""

from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ASYNC_DRIVER = "postgresql+asyncpg://"
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The default matches docker-compose.yml. It is a local development
    # credential, not a secret. Production sets DATABASE_URL.
    database_url: str = (
        "postgresql+asyncpg://recruitdesk:recruitdesk@localhost:5433/recruitdesk"
    )

    # Secrets have no default on purpose: the app must not start without them.
    # The pepper keys the hashes of the access codes (PRD F0).
    access_code_pepper: SecretStr
    # Signs the session cookie. Separate from the pepper, so sessions can be
    # invalidated without invalidating the access codes.
    session_secret: SecretStr

    # Secure cookies are only sent over HTTPS. Chrome and Firefox make an
    # exception for http://localhost; set this to false for Safari in development.
    cookie_secure: bool = True
    session_idle_hours: int = 24

    # Shown with the "code used up" message, for example a LinkedIn profile URL.
    contact_url: str | None = None

    # Brute-force protection on the code entry endpoint.
    failed_attempts_per_ip: int = 10
    failed_attempts_window_minutes: int = 15
    failed_attempts_global_per_hour: int = 100

    @field_validator("database_url")
    @classmethod
    def use_async_driver(cls, value: str) -> str:
        """Hosts such as Railway hand out `postgresql://` URLs; we need asyncpg."""
        value = value.strip()
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return ASYNC_DRIVER + value.removeprefix(prefix)
        return value

    @field_validator("access_code_pepper", "session_secret")
    @classmethod
    def long_enough(cls, value: SecretStr) -> SecretStr:
        value = SecretStr(value.get_secret_value().strip())
        if len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            raise ValueError(f"must be at least {MIN_SECRET_LENGTH} characters")
        return value

    @field_validator("contact_url")
    @classmethod
    def empty_means_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
