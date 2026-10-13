"""Application settings, read from the environment (and `.env` in development)."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ASYNC_DRIVER = "postgresql+asyncpg://"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The default matches docker-compose.yml. It is a local development
    # credential, not a secret. Production sets DATABASE_URL.
    database_url: str = (
        "postgresql+asyncpg://recruitdesk:recruitdesk@localhost:5433/recruitdesk"
    )

    @field_validator("database_url")
    @classmethod
    def use_async_driver(cls, value: str) -> str:
        """Hosts such as Railway hand out `postgresql://` URLs; we need asyncpg."""
        value = value.strip()
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return ASYNC_DRIVER + value.removeprefix(prefix)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
