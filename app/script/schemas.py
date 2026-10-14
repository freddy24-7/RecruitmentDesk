"""The selection script: the screening criteria for one vacancy (PRD F5).

A script is a list of items. An item names one or more alternative keywords
("AWS", "Azure", "GCP"): any one of them meets it. It may ask for a number of
years, and it is either a hard or a soft requirement.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_ITEMS = 15
MAX_ALTERNATIVES = 4
KEYWORD_MAX = 80
REASON_MAX = 400
MAX_YEARS = 20


class Kind(StrEnum):
    # Must be met for a candidate to be listed (unless too few meet it).
    HARD = "hard"
    # Adds to the score, but is not required.
    SOFT = "soft"


def tidy_keywords(values: list[str]) -> list[str]:
    """Strip, drop empties and duplicates (ignoring case), keep the order."""
    seen: set[str] = set()
    tidy = []
    for value in values:
        keyword = " ".join(value.split())
        if keyword and keyword.lower() not in seen:
            seen.add(keyword.lower())
            tidy.append(keyword)
    return tidy


class ScriptItem(BaseModel):
    """One criterion, as stored and as edited by the recruiter."""

    model_config = ConfigDict(extra="forbid")

    # Alternatives: a candidate meets the item with any one of them.
    any_of: list[str]
    # Years of experience asked for. 0 means: it only has to be there.
    min_years: Annotated[int, Field(ge=0, le=MAX_YEARS)] = 0
    kind: Kind
    # The sentence in the vacancy this item is based on. Empty for an item
    # the recruiter added.
    reason: Annotated[str, Field(max_length=REASON_MAX)] = ""
    # Set by code, never by the model: is `reason` really in the vacancy text?
    grounded: bool = False
    # Set by code: the section of the vacancy the reason was found in
    # (for example "required_qualifications"), or "" if it was not found.
    source: str = ""
    # Set by code when it changed the model's proposal, to say why.
    note: Annotated[str, Field(max_length=REASON_MAX)] = ""
    # A disabled item is kept in the script but ignored when screening.
    enabled: bool = True

    @field_validator("any_of")
    @classmethod
    def usable_keywords(cls, value: list[str]) -> list[str]:
        keywords = tidy_keywords(value)
        if not 1 <= len(keywords) <= MAX_ALTERNATIVES:
            raise ValueError(f"needs 1 to {MAX_ALTERNATIVES} keywords")
        if any(len(keyword) > KEYWORD_MAX for keyword in keywords):
            raise ValueError(f"a keyword has at most {KEYWORD_MAX} characters")
        return keywords

    @field_validator("reason")
    @classmethod
    def tidy_reason(cls, value: str) -> str:
        return " ".join(value.split())


class ScriptItems(BaseModel):
    """What the recruiter submits from the dialog."""

    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[ScriptItem], Field(min_length=1, max_length=MAX_ITEMS)]

    @field_validator("items")
    @classmethod
    def something_to_screen_on(cls, value: list[ScriptItem]) -> list[ScriptItem]:
        if not any(item.enabled for item in value):
            raise ValueError("at least one item must be enabled")
        return value


# --- What the model returns ----------------------------------------------------


class ProposedItem(BaseModel):
    """One item as the model proposes it.

    Plain types only (strings, a number, a boolean), so the JSON schema sent
    to the API has no keywords a strict mode may refuse. Limits are checked
    by validators.
    """

    model_config = ConfigDict(extra="forbid")

    any_of: list[str]
    min_years: int
    hard: bool
    # The exact sentence or phrase from the vacancy that this item comes from.
    reason: str

    @field_validator("any_of")
    @classmethod
    def usable_keywords(cls, value: list[str]) -> list[str]:
        keywords = [k for k in tidy_keywords(value) if len(k) <= KEYWORD_MAX]
        if not keywords:
            raise ValueError("needs at least one keyword")
        return keywords[:MAX_ALTERNATIVES]

    @field_validator("min_years")
    @classmethod
    def plausible(cls, value: int) -> int:
        if not 0 <= value <= MAX_YEARS:
            raise ValueError(f"min_years must be between 0 and {MAX_YEARS}")
        return value

    @field_validator("reason")
    @classmethod
    def tidy_reason(cls, value: str) -> str:
        return " ".join(value.split())[:REASON_MAX]


class ScriptProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProposedItem]

    @field_validator("items")
    @classmethod
    def a_usable_number(cls, value: list[ProposedItem]) -> list[ProposedItem]:
        if not value:
            raise ValueError("needs at least one item")
        return value[:MAX_ITEMS]
