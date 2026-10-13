import uuid

from app.access.sessions import read_workspace_id, sign_workspace_id
from app.config import Settings

WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


def settings(
    session_secret: str = "fake-session-secret-for-tests-only-0123456789",
) -> Settings:
    return Settings(
        access_code_pepper="fake-pepper-for-tests-only-0123456789abcdef",
        session_secret=session_secret,
        _env_file=None,
    )


def test_a_signed_cookie_gives_back_the_workspace_id() -> None:
    token = sign_workspace_id(WORKSPACE_ID, settings())

    assert read_workspace_id(token, settings()) == WORKSPACE_ID
    # Signed, not encrypted: the id is readable, but cannot be changed.
    assert token != str(WORKSPACE_ID)


def test_a_tampered_cookie_is_rejected() -> None:
    token = sign_workspace_id(WORKSPACE_ID, settings())
    tampered = ("A" if token[0] != "A" else "B") + token[1:]

    assert read_workspace_id(tampered, settings()) is None


def test_a_cookie_signed_with_another_secret_is_rejected() -> None:
    other = settings("another-session-secret-for-tests-0123456789abc")
    token = sign_workspace_id(WORKSPACE_ID, other)

    assert read_workspace_id(token, settings()) is None


def test_missing_or_meaningless_cookies_are_rejected() -> None:
    for token in (None, "", "garbage", "a.b.c"):
        assert read_workspace_id(token, settings()) is None
