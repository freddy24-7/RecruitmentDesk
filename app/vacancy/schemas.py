"""The shapes of a vacancy: what the user chooses and what the model returns."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

TITLE_MAX = 120
COMPANY_MAX = 80
EMPHASIS_MAX = 500
SECTION_TEXT_MAX = 3000
LIST_ITEM_MAX = 400
LIST_MAX_ITEMS = 15


class Sector(StrEnum):
    IT = "IT and software"
    HEALTHCARE = "Healthcare"
    FINANCE = "Finance"
    LOGISTICS = "Logistics"
    PUBLIC = "Public sector"
    EDUCATION = "Education"
    RETAIL = "Retail"
    ENERGY = "Energy"
    ENGINEERING = "Engineering and manufacturing"
    MARKETING = "Marketing"
    LEGAL = "Legal"


class Seniority(StrEnum):
    JUNIOR = "junior"
    MEDIOR = "medior"
    SENIOR = "senior"
    LEAD = "lead"


class WorkMode(StrEnum):
    OFFICE = "office-based"
    HOME = "home-based"
    HYBRID = "hybrid"


def _in_enum_order[E: StrEnum](values: list[E], enum: type[E]) -> list[E]:
    """Remove duplicates and sort, so the same choices always look the same."""
    return [member for member in enum if member in values]


class VacancyParameters(BaseModel):
    """The choices in the "Generate vacancy" dialog (PRD F1)."""

    model_config = ConfigDict(extra="forbid")

    sector: Sector
    seniority: Annotated[list[Seniority], Field(min_length=1, max_length=4)]
    work_mode: Annotated[list[WorkMode], Field(min_length=1, max_length=3)]
    title: Annotated[str, Field(min_length=2, max_length=TITLE_MAX)]
    company: Annotated[str | None, Field(max_length=COMPANY_MAX)] = None
    emphasis: Annotated[str | None, Field(max_length=EMPHASIS_MAX)] = None

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("company", "emphasis", mode="before")
    @classmethod
    def empty_means_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("seniority")
    @classmethod
    def order_seniority(cls, value: list[Seniority]) -> list[Seniority]:
        return _in_enum_order(value, Seniority)

    @field_validator("work_mode")
    @classmethod
    def order_work_mode(cls, value: list[WorkMode]) -> list[WorkMode]:
        return _in_enum_order(value, WorkMode)


class VacancySections(BaseModel):
    """What the model must return: structured sections, not one blob (PRD F1).

    The limits below are checked by validators, not written as JSON-schema
    keywords. The schema sent to the API therefore stays plain (strings and
    lists of strings), which every structured-output mode supports.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    company_intro: str
    role_summary: str
    responsibilities: list[str]
    required_qualifications: list[str]
    nice_to_haves: list[str]
    what_we_offer: list[str]
    location_and_work_mode: str

    @field_validator("title", "company_intro", "role_summary", "location_and_work_mode")
    @classmethod
    def text_present(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        if len(value) > SECTION_TEXT_MAX:
            raise ValueError("too long")
        return value

    @field_validator(
        "responsibilities", "required_qualifications", "nice_to_haves", "what_we_offer"
    )
    @classmethod
    def clean_items(cls, value: list[str]) -> list[str]:
        items = [item.strip() for item in value if item.strip()]
        if len(items) > LIST_MAX_ITEMS:
            raise ValueError("too many items")
        if any(len(item) > LIST_ITEM_MAX for item in items):
            raise ValueError("item too long")
        return items

    @field_validator("responsibilities", "required_qualifications", "what_we_offer")
    @classmethod
    def at_least_one(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("needs at least one item")
        return value
