"""Interview questions: what the model returns, and what is stored (PRD F8)."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

QUESTION_MAX = 400
PURPOSE_MAX = 300
MAX_QUESTIONS = 12


def _tidy(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


class ProposedQuestion(BaseModel):
    """One question as the model proposes it. Plain types only."""

    model_config = ConfigDict(extra="forbid")

    question: str
    # What the question is meant to find out.
    purpose: str
    # The reference of what the question is based on, as given in the prompt:
    # "S2" for a script item, "P1" for a strength, "C1" for a concern.
    source: str

    @field_validator("question", "purpose")
    @classmethod
    def present(cls, value: str) -> str:
        value = _tidy(value, QUESTION_MAX)
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("source")
    @classmethod
    def tidy_source(cls, value: str) -> str:
        return value.strip().upper()


class ProposedQuestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[ProposedQuestion]

    @field_validator("questions")
    @classmethod
    def a_usable_number(cls, value: list[ProposedQuestion]) -> list[ProposedQuestion]:
        if not value:
            raise ValueError("needs at least one question")
        return value[:MAX_QUESTIONS]


class Source(BaseModel):
    """What a question is based on, as code looked it up."""

    kind: str  # "script_item", "strength", "concern" or "recruiter"
    text: str


class Question(BaseModel):
    """A question as stored and as edited by the recruiter."""

    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=QUESTION_MAX)]
    purpose: Annotated[str, Field(max_length=PURPOSE_MAX)] = ""
    # A reference into the set's sources, or "" for a question the recruiter
    # wrote. Checked by the server, which also fills in what it refers to.
    source: str = ""
    source_kind: str = "recruiter"
    source_text: str = ""
    # Terms a check in code found that may touch a protected attribute.
    flags: list[str] = []

    @field_validator("question", "purpose", mode="before")
    @classmethod
    def tidy(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value


class QuestionsIn(BaseModel):
    """What the recruiter saves from the editor."""

    model_config = ConfigDict(extra="forbid")

    questions: Annotated[list[Question], Field(min_length=1, max_length=MAX_QUESTIONS)]
