"""Prompts are versioned files in prompts/, not inline strings.

The file name is the version (for example `vacancy_v1`) and is stored with
each generated result. A prompt file has a `## system` and a `## user` part.
The user part may contain `$name` placeholders.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
SYSTEM_MARKER = "## system"
USER_MARKER = "## user"


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    user_template: str

    def render_user(self, variables: dict[str, str]) -> str:
        # substitute (not safe_substitute): a missing value is a bug, not a
        # prompt with a literal "$name" in it.
        return Template(self.user_template).substitute(variables)


@lru_cache
def load_prompt(version: str) -> Prompt:
    text = (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
    if SYSTEM_MARKER not in text or USER_MARKER not in text:
        raise ValueError(f"prompt {version} needs a '## system' and a '## user' part")
    system, user = text.split(SYSTEM_MARKER, 1)[1].split(USER_MARKER, 1)
    return Prompt(version=version, system=system.strip(), user_template=user.strip())
