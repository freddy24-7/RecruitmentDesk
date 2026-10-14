"""What the model returns when it assesses one candidate (PRD F6)."""

from pydantic import BaseModel, ConfigDict, field_validator

POINT_MAX = 400
REASONING_MAX = 1500
MAX_POINTS = 6
MAX_CLAIMS = 30


def _tidy(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


class KeywordClaim(BaseModel):
    """The model says: this keyword is in the CV, with this many years."""

    model_config = ConfigDict(extra="forbid")

    keyword: str
    years: float

    @field_validator("keyword")
    @classmethod
    def tidy(cls, value: str) -> str:
        value = _tidy(value, 80)
        if not value:
            raise ValueError("keyword must not be empty")
        return value

    @field_validator("years")
    @classmethod
    def plausible(cls, value: float) -> float:
        if not 0 <= value <= 60:
            raise ValueError("years must be between 0 and 60")
        return value


class Point(BaseModel):
    """A strength or a concern, with the script keywords it rests on.

    For a strength: keywords the candidate has. For a concern: keywords the
    candidate lacks. Naming them lets code check the point against the CV.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    keywords: list[str]

    @field_validator("text")
    @classmethod
    def present(cls, value: str) -> str:
        value = _tidy(value, POINT_MAX)
        if not value:
            raise ValueError("text must not be empty")
        return value

    @field_validator("keywords")
    @classmethod
    def tidy(cls, value: list[str]) -> list[str]:
        return [k for k in (_tidy(v, 80) for v in value) if k][:10]


class ModelAssessment(BaseModel):
    """Plain types only, so the JSON schema has nothing a strict mode may refuse."""

    model_config = ConfigDict(extra="forbid")

    # 0 (no fit) to 100 (excellent fit).
    fit_score: int
    found: list[KeywordClaim]
    strengths: list[Point]
    concerns: list[Point]
    reasoning: str

    @field_validator("fit_score")
    @classmethod
    def in_range(cls, value: int) -> int:
        if not 0 <= value <= 100:
            raise ValueError("fit_score must be between 0 and 100")
        return value

    @field_validator("found")
    @classmethod
    def not_too_many_claims(cls, value: list[KeywordClaim]) -> list[KeywordClaim]:
        return value[:MAX_CLAIMS]

    @field_validator("strengths", "concerns")
    @classmethod
    def not_too_many_points(cls, value: list[Point]) -> list[Point]:
        return value[:MAX_POINTS]

    @field_validator("reasoning")
    @classmethod
    def present(cls, value: str) -> str:
        value = _tidy(value, REASONING_MAX)
        if not value:
            raise ValueError("reasoning must not be empty")
        return value
