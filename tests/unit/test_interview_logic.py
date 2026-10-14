"""Interview questions: links to their sources, rechecks after edits, and flags."""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.interview.guardrails import flags_for
from app.interview.schemas import ProposedQuestions, Question, QuestionsIn, Source
from app.interview.service import (
    BROKEN_LINK,
    assessment_sources,
    link_questions,
    recheck,
    script_sources,
)

SOURCES = {
    "S1": Source(kind="script_item", text="AWS or Azure (required, at least 5 years)"),
    "P1": Source(kind="strength", text="Long hands-on Azure experience."),
    "C1": Source(kind="concern", text="No container orchestration."),
}


def proposed(*items: tuple[str, str]) -> ProposedQuestions:
    return ProposedQuestions.model_validate(
        {
            "questions": [
                {"question": question, "purpose": "Shows it.", "source": source}
                for question, source in items
            ]
        }
    )


def test_questions_are_linked_to_the_source_they_name() -> None:
    kept, dropped = link_questions(
        proposed(
            ("Tell me about your Azure work.", "p1"),
            ("How do you run containers?", "C1"),
        ),
        SOURCES,
    )

    assert dropped == []
    assert [(q.source, q.source_kind, q.source_text) for q in kept] == [
        ("P1", "strength", "Long hands-on Azure experience."),
        ("C1", "concern", "No container orchestration."),
    ]


def test_a_question_with_a_broken_link_is_dropped_and_reported() -> None:
    """Broken on purpose: the model names sources that were never given."""
    kept, dropped = link_questions(
        proposed(
            ("A fair question.", "S1"), ("An invented basis.", "P7"), ("No basis.", "")
        ),
        SOURCES,
    )

    assert [q.question for q in kept] == ["A fair question."]
    assert dropped == [
        {"kind": BROKEN_LINK, "detail": "P7"},
        {"kind": BROKEN_LINK, "detail": "(none)"},
    ]


def test_questions_rest_only_on_what_survived_the_evidence_check() -> None:
    """The assessment row holds the checked strengths and concerns only."""
    checked = SimpleNamespace(
        strengths=["Long hands-on Azure experience."],
        concerns=["No container orchestration.", "Short time in a lead role."],
    )

    sources = assessment_sources(checked)  # type: ignore[arg-type]

    assert {ref: s.kind for ref, s in sources.items()} == {
        "P1": "strength",
        "C1": "concern",
        "C2": "concern",
    }


def test_script_sources_cover_the_enabled_items_only() -> None:
    script = SimpleNamespace(
        items=[
            {"any_of": ["AWS", "Azure"], "min_years": 5, "kind": "hard"},
            {"any_of": ["COBOL"], "min_years": 0, "kind": "hard", "enabled": False},
            {"any_of": ["Scrum"], "min_years": 0, "kind": "soft"},
        ]
    )

    sources = script_sources(script)  # type: ignore[arg-type]

    assert {ref: s.text for ref, s in sources.items()} == {
        "S1": "AWS or Azure (required, at least 5 years)",
        "S3": "Scrum (nice to have)",
    }


def test_after_an_edit_the_server_decides_the_source_and_the_flags() -> None:
    stored = {ref: source.model_dump() for ref, source in SOURCES.items()}
    sent = [
        # A tampered source text is replaced by the real one.
        Question(
            question="About Azure?", source="P1", source_text="Anything", flags=[]
        ),
        # An unknown reference makes it the recruiter's own question.
        Question(
            question="Where do you see yourself?", source="X9", source_kind="strength"
        ),
        # Flags are computed again, whatever the browser sent.
        Question(question="Do you have children?", flags=[]),
    ]

    checked = recheck(sent, stored)

    assert [(q.source, q.source_kind, q.source_text) for q in checked] == [
        ("P1", "strength", "Long hands-on Azure experience."),
        ("", "recruiter", ""),
        ("", "recruiter", ""),
    ]
    assert checked[2].flags == ["children (family)"]


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("How old are you?", "how old (age)"),
        ("Do you plan to have children soon?", "children (family)"),
        ("Are you pregnant?", "pregnant (family)"),
        ("Where are you originally from?", "where are you originally from (origin)"),
        ("Which religion do you follow?", "religion (religion)"),
        ("Will your health allow the travel?", "your health (health)"),
        ("What does your wife think of the hours?", "wife (family status)"),
        ("Is English your mother tongue?", "mother tongue (origin)"),
    ],
)
def test_questions_about_protected_attributes_are_flagged(text: str, flag: str) -> None:
    assert flag in flags_for(text)


@pytest.mark.parametrize(
    "text",
    [
        "Tell me about a time you partnered with a security team.",
        "How do you assess a patient's health care needs?",
        "Describe a project where you mentored a junior engineer.",
        "How did you handle a production outage?",
    ],
)
def test_ordinary_interview_questions_are_not_flagged(text: str) -> None:
    assert flags_for(text) == []


@pytest.mark.parametrize(
    "questions",
    [
        [],
        [{"question": ""}],
        [{"question": "x" * 401}],
        [{"question": "Fine?", "purpose": "x" * 301}],
        [{"question": "Fine?"}] * 13,
        [{"question": "Fine?", "weight": 2}],
    ],
)
def test_an_invalid_edit_is_refused(questions: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        QuestionsIn.model_validate({"questions": questions})


def test_an_empty_proposal_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProposedQuestions.model_validate({"questions": []})
