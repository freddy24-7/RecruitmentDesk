"""The shapes used for candidates: profile, blueprint, model output and CV."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.candidates.text import overlap

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
    """One requirement of the vacancy: any one of the named skills meets it.

    A vacancy that asks for "AWS, Azure or GCP" has one need with three
    alternatives, not three needs.
    """

    model_config = ConfigDict(extra="forbid")

    any_of: list[str]
    # Years of experience the vacancy asks for. 0 when it names no number.
    min_years: int

    @field_validator("any_of")
    @classmethod
    def tidy(cls, value: list[str]) -> list[str]:
        return _tidy_names(value)

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
        # No skill name may contain another ("AWS" and "AWS CDK"). Otherwise a
        # CV that names one would also name the other, and a candidate could
        # not have the first without seeming to have the second. The name that
        # comes first is kept.
        taken: list[str] = []

        def free(names: list[str], limit: int) -> list[str]:
            kept: list[str] = []
            for name in names:
                if len(kept) < limit and not any(overlap(name, t) for t in taken):
                    taken.append(name)
                    kept.append(name)
            return kept

        needs: list[SkillNeed] = []
        for need in self.required_skills:
            alternatives = free(need.any_of, limit=4)
            if alternatives and len(needs) < 8:
                needs.append(SkillNeed(any_of=alternatives, min_years=need.min_years))
        if len(needs) < 2:
            raise ValueError("at least two required skills are needed")
        self.required_skills = needs
        self.nice_skills = free(_tidy_names(self.nice_skills), limit=6)

        # A neighbouring or unrelated job must not bring the vacancy's own
        # skills along, or the planted match category would be wrong.
        vacancy_skills = list(taken)
        for roles in (self.adjacent_roles, self.unrelated_roles):
            for role in roles:
                role.skills = [
                    skill
                    for skill in role.skills
                    if not any(overlap(skill, taken) for taken in vacancy_skills)
                ][:6]
        self.adjacent_roles = [r for r in self.adjacent_roles if r.skills][:5]
        self.unrelated_roles = [r for r in self.unrelated_roles if r.skills][:5]
        if not self.adjacent_roles or not self.unrelated_roles:
            raise ValueError("adjacent and unrelated roles with skills are needed")
        return self

    @property
    def vacancy_skills(self) -> list[str]:
        """Every skill the vacancy names: all alternatives, and the nice-to-haves."""
        required = [name for need in self.required_skills for name in need.any_of]
        return required + self.nice_skills


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
    # Vacancy skills this candidate has. Each may only be named in the jobs
    # where it was used, because years are computed from those jobs.
    tracked_skills: list[str] = []
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
