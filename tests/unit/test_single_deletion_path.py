"""One deletion path for vacancy data (CLAUDE.md rule 8).

Only app/vacancy/deletion.py may delete rows. The check parses the source
files, and is also run against a tree with a second deletion path.
"""

import ast
from pathlib import Path

import pytest

from app.vacancy.deletion import ConfirmationRequired, delete_vacancy

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {Path("app/vacancy/deletion.py")}
SESSION_NAMES = {"session", "db"}
RAW_SQL = ("DELETE FROM", "TRUNCATE")


def deletion_sites(root: Path) -> list[str]:
    """Files under app/ that delete rows, other than the allowed module."""
    offenders = []
    for path in sorted((root / "app").rglob("*.py")):
        relative = path.relative_to(root)
        if relative in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            deletes = False
            if isinstance(node, ast.Call):
                called = node.func
                # sqlalchemy.delete(...)
                if isinstance(called, ast.Name) and called.id == "delete":
                    deletes = True
                # session.delete(...)
                if (
                    isinstance(called, ast.Attribute)
                    and called.attr == "delete"
                    and isinstance(called.value, ast.Name)
                    and called.value.id in SESSION_NAMES
                ):
                    deletes = True
            # Raw SQL in a string. Docstrings may mention the words.
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any(sql in node.value.upper() for sql in RAW_SQL)
                and not _is_docstring(tree, node)
            ):
                deletes = True
            if deletes and str(relative) not in offenders:
                offenders.append(str(relative))
    return offenders


def _is_docstring(tree: ast.AST, constant: ast.Constant) -> bool:
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and body[0].value is constant:
                return True
    return False


def test_only_the_deletion_module_deletes_rows() -> None:
    assert deletion_sites(REPO_ROOT) == []


def test_the_allowed_module_really_deletes() -> None:
    """Otherwise the check above could pass because it looks for the wrong thing."""
    source = (REPO_ROOT / "app/vacancy/deletion.py").read_text(encoding="utf-8")

    assert "delete(Vacancy)" in source


def test_the_check_catches_a_second_deletion_path(tmp_path: Path) -> None:
    (tmp_path / "app" / "vacancy").mkdir(parents=True)
    (tmp_path / "app" / "web").mkdir()
    (tmp_path / "app" / "jobs").mkdir()
    (tmp_path / "app" / "vacancy" / "deletion.py").write_text(
        "from sqlalchemy import delete\nstatement = delete(object)\n"
    )
    (tmp_path / "app" / "vacancy" / "review.py").write_text(
        "from sqlalchemy import delete\nstatement = delete(object)\n"
    )
    (tmp_path / "app" / "web" / "vacancies.py").write_text(
        "async def remove(session, vacancy):\n    await session.delete(vacancy)\n"
    )
    (tmp_path / "app" / "jobs" / "cleanup.py").write_text(
        'SQL = "delete from vacancy where id = 1"\n'
    )
    (tmp_path / "app" / "web" / "routes.py").write_text(
        '"""Routes. DELETE FROM is only mentioned here."""\n'
        "def register(router):\n    router.delete('/x')\n"
    )

    assert deletion_sites(tmp_path) == [
        "app/jobs/cleanup.py",
        "app/vacancy/review.py",
        "app/web/vacancies.py",
    ]


async def test_the_deletion_function_itself_refuses_without_confirmation() -> None:
    """The flag is checked before anything else, so no session is even needed."""
    with pytest.raises(ConfirmationRequired):
        await delete_vacancy(None, None, confirmed=False)  # type: ignore[arg-type]
