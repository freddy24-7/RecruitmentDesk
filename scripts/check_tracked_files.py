"""Fail if Git tracks a file that could hold access codes or secrets.

Access codes live only in the developer's password manager and, as keyed
hashes, in the database (PRD F0). This check runs in CI:

    uv run python scripts/check_tracked_files.py
"""

import re
import subprocess
import sys
from pathlib import PurePosixPath

# A data file whose name says it holds codes, for example `codes.txt` or
# `access-codes.csv`. Python sources such as `manage_codes.py` are allowed.
CODES_FILE = re.compile(r"codes?\.(txt|csv|tsv|json|ya?ml|md|env|xlsx?)$")

ALLOWED_ENV_FILES = {".env.example"}


def forbidden_reason(path: str) -> str | None:
    """Return why `path` must not be tracked, or None if it is fine."""
    name = PurePosixPath(path).name.lower()
    if name not in ALLOWED_ENV_FILES and (name == ".env" or name.startswith(".env.")):
        return "environment file (may contain secrets)"
    if CODES_FILE.search(name):
        return "looks like a file with access codes"
    return None


def find_forbidden(paths: list[str]) -> list[tuple[str, str]]:
    found = []
    for path in paths:
        reason = forbidden_reason(path)
        if reason is not None:
            found.append((path, reason))
    return found


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


def main() -> int:
    found = find_forbidden(tracked_files())
    for path, reason in found:
        print(f"Tracked file not allowed: {path} ({reason})", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
