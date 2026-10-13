import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.llm.base import LlmRequest
from app.llm.fake import fake_vacancy
from app.vacancy.schemas import VacancyParameters, VacancySections

CHOICES: dict[str, Any] = {
    "sector": "IT and software",
    "seniority": ["senior"],
    "work_mode": ["hybrid"],
    "title": "Cloud Engineer",
}

SECTIONS: dict[str, Any] = {
    "title": "Cloud Engineer",
    "company_intro": "A fictional company.",
    "role_summary": "You build cloud platforms.",
    "responsibilities": ["Build", "Run"],
    "required_qualifications": ["3 years of experience with Microsoft Azure"],
    "nice_to_haves": [],
    "what_we_offer": ["A salary"],
    "location_and_work_mode": "Utrecht, hybrid.",
}


def test_valid_choices_are_accepted_and_tidied() -> None:
    parameters = VacancyParameters.model_validate(
        CHOICES
        | {
            "title": "  Cloud Engineer  ",
            "seniority": ["lead", "junior", "lead"],
            "work_mode": ["hybrid", "office-based"],
            "company": "   ",
            "emphasis": " Team lead experience ",
        }
    )

    assert parameters.title == "Cloud Engineer"
    # Duplicates are removed and the order is always the same.
    assert [level.value for level in parameters.seniority] == ["junior", "lead"]
    assert [mode.value for mode in parameters.work_mode] == ["office-based", "hybrid"]
    assert parameters.company is None
    assert parameters.emphasis == "Team lead experience"


@pytest.mark.parametrize(
    "change",
    [
        {"sector": "Astrology"},
        {"seniority": []},
        {"seniority": ["expert"]},
        {"work_mode": []},
        {"work_mode": ["on the moon"]},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 121},
        {"company": "x" * 81},
        {"emphasis": "x" * 501},
        {"unknown_field": "value"},
    ],
)
def test_invalid_choices_are_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VacancyParameters.model_validate(CHOICES | change)


def test_valid_sections_are_accepted_and_tidied() -> None:
    sections = VacancySections.model_validate(
        SECTIONS | {"responsibilities": ["  Build  ", "", "Run"], "title": " Cloud "}
    )

    assert sections.responsibilities == ["Build", "Run"]
    assert sections.title == "Cloud"
    # Nice-to-haves may be empty; the other lists may not.
    assert sections.nice_to_haves == []


@pytest.mark.parametrize(
    "change",
    [
        {"title": ""},
        {"role_summary": "   "},
        {"responsibilities": []},
        {"responsibilities": ["", " "]},
        {"required_qualifications": []},
        {"what_we_offer": []},
        {"responsibilities": ["x"] * 16},
        {"responsibilities": ["x" * 401]},
        {"company_intro": "x" * 3001},
        {"responsibilities": "one long string"},
        {"extra_section": "text"},
    ],
)
def test_invalid_sections_are_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VacancySections.model_validate(SECTIONS | change)


def test_a_missing_section_is_refused() -> None:
    incomplete = {k: v for k, v in SECTIONS.items() if k != "what_we_offer"}

    with pytest.raises(ValidationError):
        VacancySections.model_validate(incomplete)


def test_json_schema_for_the_api_stays_plain() -> None:
    """Limits are checked in code, so the schema has no keywords an API may refuse."""
    schema = json.dumps(VacancySections.model_json_schema())

    for keyword in ("minLength", "maxLength", "minItems", "maxItems", "pattern"):
        assert keyword not in schema


def test_the_fake_model_returns_a_valid_vacancy() -> None:
    request = LlmRequest(
        call_type="vacancy",
        model="fake",
        system="",
        user="",
        schema=VacancySections,
        temperature=0,
        max_tokens=1,
        variables={"title": "Cloud Engineer", "sector": "Finance"},
    )

    sections = VacancySections.model_validate_json(fake_vacancy(request))

    assert sections.title == "Cloud Engineer"
    assert "Fake model output" in sections.company_intro
