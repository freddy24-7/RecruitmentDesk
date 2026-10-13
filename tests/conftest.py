"""Test configuration. Set before any application module reads its settings.

Tests never use the development database: they use a database whose name
ends in `_test`, on the server from DATABASE_URL (CI) or docker-compose.yml.
All secrets here are obviously fake.
"""

import os

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

LOCAL_DATABASE = (
    "postgresql+asyncpg://recruitdesk:recruitdesk@localhost:5433/recruitdesk"
)

_base = make_url(os.environ.get("DATABASE_URL", LOCAL_DATABASE))
_test_database = f"{_base.database}_test"

os.environ["DATABASE_URL"] = _base.set(database=_test_database).render_as_string(
    hide_password=False
)
os.environ["ACCESS_CODE_PEPPER"] = "fake-pepper-for-tests-only-0123456789abcdef"
os.environ["SESSION_SECRET"] = "fake-session-secret-for-tests-only-0123456789"
os.environ["COOKIE_SECURE"] = "true"
os.environ["CONTACT_URL"] = "https://example.com/contact"
os.environ["SESSION_IDLE_HOURS"] = "24"
os.environ["FAILED_ATTEMPTS_PER_IP"] = "10"
os.environ["FAILED_ATTEMPTS_WINDOW_MINUTES"] = "15"
os.environ["FAILED_ATTEMPTS_GLOBAL_PER_HOUR"] = "100"
# Tests never call the real model. The key is moved aside, where only the
# tests marked `mistral` (run on request) look for it.
os.environ["RECRUITDESK_REAL_MISTRAL_API_KEY"] = (
    os.environ.get("MISTRAL_API_KEY")
    or dotenv_values(".env").get("MISTRAL_API_KEY")
    or ""
)
os.environ["LLM_PROVIDER"] = "fake"
os.environ["MISTRAL_API_KEY"] = ""
os.environ["MISTRAL_MODEL_VACANCY"] = "mistral-small-2603"
os.environ["FAKE_LLM_DELAY_SECONDS"] = "0"
os.environ["MAX_VACANCY_GENERATIONS_PER_WORKSPACE"] = "10"
# Tests do not depend on whether the frontend happens to be built.
os.environ["FRONTEND_DIST"] = "does-not-exist"
os.environ["MISTRAL_MODEL_CV"] = "mistral-small-2603"
os.environ["CV_CONCURRENCY"] = "4"
os.environ["MAX_CANDIDATES_PER_WORKSPACE"] = "300"
os.environ["BLUEPRINT_SEED"] = "20261013"
os.environ["MISTRAL_MODEL_SCRIPT"] = "mistral-small-2603"
os.environ["MAX_SCRIPT_PROPOSALS_PER_WORKSPACE"] = "20"
