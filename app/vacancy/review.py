"""Reviewing a vacancy: edit, reset to the generated text, submit (PRD F2, F3)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.vacancy.guardrails import find_flags
from app.vacancy.models import DRAFT, SUBMITTED, Vacancy
from app.vacancy.schemas import DraftSections, empty_required_sections

EDITABLE = (DRAFT, SUBMITTED)


class NotAllowed(Exception):
    """The action does not fit the state the vacancy is in."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(kind)
        self.kind = kind
        self.message = message


class SectionsIncomplete(Exception):
    def __init__(self, empty: list[str]) -> None:
        super().__init__("sections_incomplete")
        self.empty = empty

    @property
    def message(self) -> str:
        return "These sections are still empty: " + ", ".join(self.empty) + "."


def _require_editable(vacancy: Vacancy) -> None:
    if vacancy.status not in EDITABLE:
        raise NotAllowed("not_editable", "This vacancy cannot be edited right now.")


def _store(vacancy: Vacancy, sections: DraftSections) -> None:
    """Save text as a new version. Callers have checked that it may be saved."""
    if vacancy.status == SUBMITTED:
        # A submitted vacancy is used by later steps: it must stay complete.
        empty = empty_required_sections(sections)
        if empty:
            raise SectionsIncomplete(empty)
    vacancy.sections = sections.model_dump(mode="json")
    vacancy.flags = [flag.model_dump() for flag in find_flags(sections)]
    vacancy.version += 1
    vacancy.updated_at = datetime.now(UTC)


def save_edits(vacancy: Vacancy, sections: DraftSections) -> bool:
    """Save edited sections as a new version. False if nothing changed."""
    _require_editable(vacancy)
    if sections.model_dump(mode="json") == vacancy.sections:
        return False
    _store(vacancy, sections)
    return True


def reset_to_generated(vacancy: Vacancy) -> bool:
    """Put back the text as the model wrote it. False if nothing changed."""
    _require_editable(vacancy)
    if vacancy.generated_sections is None:
        raise NotAllowed(
            "nothing_generated", "There is no generated text to go back to."
        )
    if vacancy.sections == vacancy.generated_sections:
        return False
    _store(vacancy, DraftSections.model_validate(vacancy.generated_sections))
    return True


def submit(vacancy: Vacancy) -> None:
    """Move a complete draft to the submitted vacancies."""
    if vacancy.status != DRAFT:
        raise NotAllowed("not_a_draft", "Only a draft can be submitted.")
    draft = DraftSections.model_validate(vacancy.sections or {})
    empty = empty_required_sections(draft)
    if empty:
        raise SectionsIncomplete(empty)
    now = datetime.now(UTC)
    vacancy.status = SUBMITTED
    vacancy.submitted_at = now
    vacancy.updated_at = now


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    enabled: bool
    # Why the action is disabled. Shown next to the button.
    reason: str | None = None


NOT_BUILT_YET = "Not available yet in this version of the demo."
JOB_RUNNING = "Wait until the running job has finished."


def available_actions(vacancy: Vacancy, *, job_running: bool) -> list[Action]:
    """The actions on a submitted vacancy, each enabled or disabled with a reason.

    One function decides this, so the API and the screen cannot disagree. An
    action whose prerequisites are missing stays visible (PRD F3).
    """
    if vacancy.status != SUBMITTED:
        return []
    return [
        Action("edit", "Edit vacancy", enabled=True),
        Action(
            "generate_candidates",
            "Generate candidates",
            enabled=not job_running,
            reason=JOB_RUNNING if job_running else None,
        ),
        Action(
            "generate_script", "Generate selection script", False, reason=NOT_BUILT_YET
        ),
        Action(
            "generate_long_list",
            "Generate long-list",
            False,
            reason="Generate candidates and a selection script first.",
        ),
        Action(
            "generate_short_list",
            "Generate short-list",
            False,
            reason="Generate candidates and a selection script first.",
        ),
    ]
