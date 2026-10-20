"""Application settings, read from the environment (and `.env` in development)."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ASYNC_DRIVER = "postgresql+asyncpg://"
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    # hide_input_in_errors: a settings error must never print a value, as
    # the values include the secrets.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    # "production" makes the app refuse to start without the protections a
    # public deployment needs (see `missing_for_production`).
    app_env: Literal["development", "production"] = "development"

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
    # The request header in which the host's proxy passes the visitor's
    # address, for example `x-real-ip` on Railway. Empty means the address of
    # the connection itself, which is right when nothing sits in between
    # (local development). Never trust a header the visitor can set.
    client_ip_header: str | None = None
    # New sessions (each one a fresh workspace with its own limits) that one
    # IP address may start per hour.
    max_sessions_per_ip_per_hour: int = 5

    # The model. `fake` answers without the network and without cost: use it
    # in development. Tests always use the fake.
    llm_provider: Literal["mistral", "fake"] = "mistral"
    mistral_api_key: SecretStr | None = None
    # Exact, pinned model versions. No `-latest` aliases (CLAUDE.md).
    mistral_model_vacancy: str = "mistral-small-2603"
    # The two calls made once per vacancy, where quality matters most and the
    # stronger model costs well under a cent (decided after the stage 6 runs):
    # reading the vacancy's requirements to plant candidates, and proposing the
    # selection script.
    mistral_model_profile: str = "mistral-medium-2604"
    mistral_model_cv: str = "mistral-small-2603"
    mistral_model_script: str = "mistral-medium-2604"
    # The model that assesses candidates. To be chosen after a comparison.
    mistral_model_assessment: str = "mistral-small-2603"
    mistral_model_interview: str = "mistral-small-2603"
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

    # How often one workspace may make interview questions.
    max_interview_runs_per_workspace: int = 10

    # The final score is this share of the facts computed by code, and the rest
    # of the model's fit score (PRD F6).
    screening_weight_deterministic: float = 0.5

    # The most all workspaces together may spend on model calls per day (UTC),
    # in US dollars, from the usage records. Empty means no cap.
    daily_spend_cap_usd: Decimal | None = Decimal("2.00")

    # Workspaces idle this long are deleted with all their data; the clean-up
    # runs this often.
    cleanup_interval_minutes: int = 60

    # Requests with a larger body are refused.
    max_request_bytes: int = 256_000

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

    @field_validator("daily_spend_cap_usd", mode="before")
    @classmethod
    def empty_cap_means_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("client_ip_header", mode="before")
    @classmethod
    def header_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() or None
        return value

    @field_validator("mistral_api_key")
    @classmethod
    def empty_key_means_none(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        return SecretStr(value.get_secret_value().strip())


def missing_for_production(settings: Settings) -> list[str]:
    """What a public deployment still needs (PRD 11). Empty when all is set.

    Checked at startup, outside the settings validation on purpose: a
    validation error prints the input values, and those include the secrets.
    """
    if settings.app_env != "production":
        return []
    missing = []
    if settings.daily_spend_cap_usd is None:
        missing.append("DAILY_SPEND_CAP_USD")
    if not settings.cookie_secure:
        missing.append("COOKIE_SECURE=true")
    if settings.client_ip_header is None:
        missing.append("CLIENT_IP_HEADER")
    if settings.llm_provider == "mistral" and settings.mistral_api_key is None:
        missing.append("MISTRAL_API_KEY")
    return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
