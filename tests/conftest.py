"""Test configuration. Set before any application module reads its settings.

Tests never use the development database: they use a database whose name
ends in `_test`, on the server from DATABASE_URL (CI) or docker-compose.yml.
All secrets here are obviously fake.
"""

import os

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
