"""Application settings, read from the environment (and `.env` in development)."""

from functools import lru_cache
from typing import Literal

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

    # The model. `fake` answers without the network and without cost: use it
    # in development. Tests always use the fake.
    llm_provider: Literal["mistral", "fake"] = "mistral"
    mistral_api_key: SecretStr | None = None
    # Exact, pinned model versions. No `-latest` aliases (CLAUDE.md).
    mistral_model_vacancy: str = "mistral-small-2603"
    mistral_model_cv: str = "mistral-small-2603"
    mistral_model_script: str = "mistral-small-2603"
    # The model that assesses candidates. To be chosen after a comparison.
    mistral_model_assessment: str = "mistral-small-2603"
    llm_timeout_seconds: int = 60
    # How many CVs are written at the same time. Low, because of rate limits.
    cv_concurrency: int = 4
    # Makes the fake slow enough to see the spinner in development.
    fake_llm_delay_seconds: float = 0.0

    # The built frontend (`npm --prefix web run build`). Served by the backend
    # when the folder exists, so the app is one service on one origin.
    frontend_dist: str = "web/dist"

    # Per-workspace limits on billable work (see app/limits/workspace.py).
    max_vacancy_generations_per_workspace: int = 10
    # Candidates one workspace may generate in total, over all its vacancies.
    max_candidates_per_workspace: int = 300

    # How often one workspace may ask the model for a selection script.
    max_script_proposals_per_workspace: int = 20

    # How often one workspace may run the screening (long list and short list).
    max_screening_runs_per_workspace: int = 10

    # The final score is this share of the facts computed by code, and the rest
    # of the model's fit score (PRD F6).
    screening_weight_deterministic: float = 0.5

    # Blueprint sampling is seeded, so a pool can be reproduced.
    blueprint_seed: int = 20261013

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

    @field_validator("mistral_api_key")
    @classmethod
    def empty_key_means_none(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        return SecretStr(value.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
