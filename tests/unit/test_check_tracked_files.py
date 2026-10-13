import pytest

from scripts.check_tracked_files import find_forbidden, forbidden_reason


@pytest.mark.parametrize(
    "path",
    [
        "codes.txt",
        "access_codes.csv",
        "docs/access-codes.md",
        "deploy/CODES.JSON",
        "code.txt",
        ".env",
        "web/.env.production",
        ".env.local",
    ],
)
def test_files_that_could_hold_codes_or_secrets_are_refused(path: str) -> None:
    assert forbidden_reason(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "scripts/manage_codes.py",
        "app/access/codes.py",
        "tests/unit/test_codes.py",
        "docs/PRD.md",
        "web/src/CodeEntry.tsx",
        "README.md",
    ],
)
def test_ordinary_source_files_are_allowed(path: str) -> None:
    assert forbidden_reason(path) is None


def test_find_forbidden_reports_only_the_offending_paths() -> None:
    found = find_forbidden(["README.md", "codes.txt", "app/main.py", ".env"])

    assert [path for path, _reason in found] == ["codes.txt", ".env"]
