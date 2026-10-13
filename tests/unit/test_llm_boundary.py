"""One door to the model (CLAUDE.md rule 1).

Only app/llm/mistral.py may import the Mistral SDK. The check parses the
source files, and is also run against a tree that breaks the rule on purpose.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED = Path("app/llm/mistral.py")
# The SDK, and the HTTP library it brings along.
SDK_MODULES = {"mistralai", "httpx2"}
SOURCE_DIRS = ("app", "scripts", "migrations")


def stray_sdk_imports(root: Path) -> list[str]:
    """Files under `root` that import the SDK but are not the allowed module."""
    offenders = []
    for directory in SOURCE_DIRS:
        for path in sorted((root / directory).rglob("*.py")):
            if path.relative_to(root) == ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                if any(module.split(".")[0] in SDK_MODULES for module in modules):
                    offenders.append(str(path.relative_to(root)))
    return offenders


def test_only_the_mistral_module_imports_the_sdk() -> None:
    assert stray_sdk_imports(REPO_ROOT) == []


def test_the_allowed_module_really_imports_the_sdk() -> None:
    """Otherwise the check above could pass because the names are wrong."""
    source = (REPO_ROOT / ALLOWED).read_text(encoding="utf-8")

    assert "from mistralai" in source


def test_the_check_catches_a_stray_import(tmp_path: Path) -> None:
    (tmp_path / "app" / "llm").mkdir(parents=True)
    (tmp_path / "app" / "vacancy").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "migrations").mkdir()
    (tmp_path / "app" / "llm" / "mistral.py").write_text("import mistralai\n")
    (tmp_path / "app" / "vacancy" / "service.py").write_text(
        "from mistralai.client import Mistral\n"
    )
    (tmp_path / "scripts" / "quick_test.py").write_text("import os, mistralai\n")

    assert stray_sdk_imports(tmp_path) == [
        "app/vacancy/service.py",
        "scripts/quick_test.py",
    ]
