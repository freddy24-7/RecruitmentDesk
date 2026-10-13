"""The shapes used for candidates: profile, blueprint, model output and CV."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

MAX_CANDIDATES = 100
NAME_MAX = 80
TEXT_MAX = 1500
ITEM_MAX = 400


def _tidy_names(values: list[str]) -> list[str]:
    """Strip, drop empties and duplicates (ignoring case), keep the order."""
    seen: set[str] = set()
    tidy = []
    for value in values:
        name = value.strip()
        if name and name.lower() not in seen and len(name) <= NAME_MAX:
            seen.add(name.lower())
            tidy.append(name)
    return tidy


# --- What the model extracts from a vacancy ----------------------------------


class SkillNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    # Years of experience the vacancy asks for. 0 when it names no number.
    min_years: int

    @field_validator("name")
    @classmethod
    def tidy(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > NAME_MAX:
            raise ValueError("skill name must be 1 to 80 characters")
        return value

    @field_validator("min_years")
    @classmethod
    def plausible(cls, value: int) -> int:
        if not 0 <= value <= 20:
            raise ValueError("min_years must be between 0 and 20")
        return value


class RoleSketch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    skills: list[str]

    @field_validator("title")
    @classmethod
    def tidy_title(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > NAME_MAX:
            raise ValueError("role title must be 1 to 80 characters")
        return value

    @field_validator("skills")
    @classmethod
    def tidy_skills(cls, value: list[str]) -> list[str]:
        return _tidy_names(value)


class VacancyProfile(BaseModel):
    """What candidate blueprints are built from (one model call per vacancy version).

    As with the vacancy sections, limits are checked by validators, so the
    JSON schema sent to the API stays plain.
    """

    model_config = ConfigDict(extra="forbid")

    required_skills: list[SkillNeed]
    nice_skills: list[str]
    # Jobs close to the vacancy, for "adjacent role" candidates.
    adjacent_roles: list[RoleSketch]
    # Jobs far from the vacancy, for "weak match" candidates.
    unrelated_roles: list[RoleSketch]

    @model_validator(mode="after")
    def usable(self) -> "VacancyProfile":
        unique: dict[str, SkillNeed] = {}
        for need in self.required_skills:
            unique.setdefault(need.name.lower(), need)
        self.required_skills = list(unique.values())[:8]
        if len(self.required_skills) < 2:
            raise ValueError("at least two required skills are needed")

        taken = set(unique)
        self.nice_skills = [
            s for s in _tidy_names(self.nice_skills) if s.lower() not in taken
        ][:6]
        taken.update(skill.lower() for skill in self.nice_skills)

        # A neighbouring or unrelated job must not bring the vacancy's own
        # skills along, or the planted match category would be wrong.
        for roles in (self.adjacent_roles, self.unrelated_roles):
            for role in roles:
                role.skills = [s for s in role.skills if s.lower() not in taken][:6]
        self.adjacent_roles = [r for r in self.adjacent_roles if r.skills][:5]
        self.unrelated_roles = [r for r in self.unrelated_roles if r.skills][:5]
        if not self.adjacent_roles or not self.unrelated_roles:
            raise ValueError("adjacent and unrelated roles with skills are needed")
        return self


# --- The blueprint: sampled by code, the ground truth -------------------------


class MatchCategory(StrEnum):
    STRONG = "strong"
    PARTIAL = "partial"
    ADJACENT = "adjacent"
    WEAK = "weak"


class BlueprintPosition(BaseModel):
    role: str
    seniority: str
    start: str  # "YYYY-MM"
    end: str | None  # None means the current job
    skills: list[str]


class Language(BaseModel):
    language: str
    level: str


class Blueprint(BaseModel):
    """One planted candidate. Kept with the candidate as ground truth.

    The match category must never reach the scoring step or the recruiter's
    screen: it is what the lists are later measured against.
    """

    index: int
    name: str
    email: str
    phone: str
    match_category: MatchCategory
    seniority: str
    years_experience: float
    positions: list[BlueprintPosition]  # most recent first
    skill_years: dict[str, float]
    # Vacancy skills this candidate does not have. The CV must not mention them.
    avoid_skills: list[str]
    education_level: str
    languages: list[Language]


# --- What the model writes for one blueprint ----------------------------------


class CvPositionText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    company: str
    highlights: list[str]

    @field_validator("title", "company")
    @classmethod
    def present(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > NAME_MAX:
            raise ValueError("must be 1 to 80 characters")
        return value

    @field_validator("highlights")
    @classmethod
    def tidy(cls, value: list[str]) -> list[str]:
        items = [item.strip() for item in value if item.strip()]
        if not 1 <= len(items) <= 8 or any(len(item) > ITEM_MAX for item in items):
            raise ValueError("needs 1 to 8 highlights of at most 400 characters")
        return items


class CvEducationText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    degree: str
    institution: str

    @field_validator("degree", "institution")
    @classmethod
    def present(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 120:
            raise ValueError("must be 1 to 120 characters")
        return value


class CvText(BaseModel):
    """The prose of a CV. Dates, skills and contact details come from code."""

    model_config = ConfigDict(extra="forbid")

    profile: str
    positions: list[CvPositionText]
    education: list[CvEducationText]

    @field_validator("profile")
    @classmethod
    def present(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > TEXT_MAX:
            raise ValueError("profile must be 1 to 1500 characters")
        return value

    @field_validator("education")
    @classmethod
    def one_or_two(cls, value: list[CvEducationText]) -> list[CvEducationText]:
        if not 1 <= len(value) <= 3:
            raise ValueError("needs 1 to 3 education entries")
        return value


# --- The CV as stored and shown ------------------------------------------------


class CvPosition(BaseModel):
    title: str
    company: str
    start: str
    end: str | None
    highlights: list[str]
    skills: list[str]


class CvEducation(BaseModel):
    degree: str
    institution: str
    year: int


class Cv(BaseModel):
    """A complete CV. It holds no name and no contact details (blind by design)."""

    profile: str
    positions: list[CvPosition]
    education: list[CvEducation]
    skills: list[str]
    languages: list[Language]
