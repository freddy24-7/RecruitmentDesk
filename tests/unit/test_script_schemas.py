"""Script items, the model's proposal, and the check that a reason is in the vacancy."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.llm.base import LlmRequest
from app.llm.fake import fake_script, fake_vacancy
from app.llm.prompts import load_prompt
from app.script.schemas import (
    Kind,
    ProposedItem,
    ScriptItem,
    ScriptItems,
    ScriptProposal,
)
from app.script.service import (
    PROMPT,
    is_grounded,
    prompt_variables,
    to_script_items,
    vacancy_text,
)
from app.vacancy.schemas import VacancySections

ITEM: dict[str, Any] = {"any_of": ["AWS", "Azure"], "min_years": 5, "kind": "hard"}


def request(call_type: str) -> LlmRequest:
    return LlmRequest(
        call_type=call_type,
        model="fake",
        system="",
        user="",
        schema=ScriptProposal,
        temperature=0,
        max_tokens=1,
        variables={"title": "Cloud Engineer"},
    )


VACANCY = VacancySections.model_validate_json(fake_vacancy(request("vacancy")))


# --- Items as the recruiter submits them -------------------------------------


def test_an_item_is_tidied() -> None:
    parsed = ScriptItem.model_validate(
        ITEM
        | {"any_of": ["  AWS ", "aws", "", "Microsoft   Azure"], "reason": " a  b "}
    )

    assert parsed.any_of == ["AWS", "Microsoft Azure"]
    assert parsed.reason == "a b"
    assert parsed.kind is Kind.HARD
    assert parsed.enabled is True
    # Whether a reason is grounded is never taken on trust.
    assert parsed.grounded is False


@pytest.mark.parametrize(
    "change",
    [
        {"any_of": []},
        {"any_of": ["", "  "]},
        {"any_of": ["a", "b", "c", "d", "e"]},
        {"any_of": ["x" * 81]},
        {"any_of": "AWS"},
        {"min_years": -1},
        {"min_years": 21},
        {"min_years": 2.5},
        {"kind": "essential"},
        {"reason": "x" * 401},
        {"weight": 3},
    ],
)
def test_an_invalid_item_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ScriptItem.model_validate(ITEM | change)


def test_a_script_needs_between_one_and_fifteen_items() -> None:
    ScriptItems.model_validate({"items": [ITEM]})
    ScriptItems.model_validate({"items": [ITEM] * 15})
    for items in ([], [ITEM] * 16):
        with pytest.raises(ValidationError):
            ScriptItems.model_validate({"items": items})


def test_a_script_needs_at_least_one_enabled_item() -> None:
    with pytest.raises(ValidationError, match="at least one item must be enabled"):
        ScriptItems.model_validate({"items": [ITEM | {"enabled": False}]})


# --- What the model returns --------------------------------------------------


def test_the_schema_for_the_api_stays_plain() -> None:
    schema = str(ScriptProposal.model_json_schema())

    for keyword in ("minLength", "maxLength", "minItems", "maxItems", "enum", "anyOf"):
        assert keyword not in schema


def test_a_proposal_is_tidied_and_cut_to_size() -> None:
    proposed = ProposedItem.model_validate(
        {
            "any_of": ["AWS", "aws", "Azure", "GCP", "Oracle Cloud", "IBM Cloud"],
            "min_years": 5,
            "hard": True,
            "reason": "  5+ years   with AWS, Azure, or GCP.  ",
        }
    )

    assert proposed.any_of == ["AWS", "Azure", "GCP", "Oracle Cloud"]
    assert proposed.reason == "5+ years with AWS, Azure, or GCP."


@pytest.mark.parametrize(
    "change",
    [{"any_of": []}, {"any_of": [""]}, {"min_years": 30}, {"min_years": -2}],
)
def test_an_unusable_proposed_item_is_refused(change: dict[str, Any]) -> None:
    base = {"any_of": ["AWS"], "min_years": 0, "hard": True, "reason": "x"}

    with pytest.raises(ValidationError):
        ProposedItem.model_validate(base | change)


def test_an_empty_proposal_is_refused() -> None:
    with pytest.raises(ValidationError):
        ScriptProposal.model_validate({"items": []})


# --- Is the reason really in the vacancy? ------------------------------------

TEXT = (
    "Senior Cloud Engineer\n"
    "5+ years of hands-on experience with AWS, Azure, or GCP.\n"
    "Experience with containerization technologies such as Docker and Kubernetes."
)


@pytest.mark.parametrize(
    "reason",
    [
        "5+ years of hands-on experience with AWS, Azure, or GCP.",
        "5+ years of hands-on experience with AWS, Azure, or GCP",
        "hands-on experience with AWS, Azure, or GCP",
        "  5+ YEARS of hands-on   experience with aws, azure, or gcp ",
        "such as Docker and Kubernetes",
    ],
)
def test_a_quote_from_the_vacancy_is_grounded(reason: str) -> None:
    assert is_grounded(reason, TEXT)


@pytest.mark.parametrize(
    "reason",
    [
        "The vacancy asks for five years of cloud experience",
        "5+ years of hands-on experience with Docker",
        "Experience with Terraform is required",
        "",
        "AWS",
    ],
)
def test_a_reason_that_is_not_in_the_vacancy_is_not_grounded(reason: str) -> None:
    """Rephrased, stitched together, invented, empty, or too short to mean much."""
    assert not is_grounded(reason, TEXT)


def test_proposed_items_become_script_items_with_the_reason_checked() -> None:
    proposal = ScriptProposal.model_validate_json(fake_script(request("script")))

    items = to_script_items(proposal, vacancy_text(VACANCY))

    assert [(i.any_of, i.min_years, i.kind.value) for i in items] == [
        (["Microsoft Azure", "AWS"], 3, "hard"),
        (["Terraform"], 2, "hard"),
        (["Kubernetes"], 0, "soft"),
        (["Scrum"], 0, "soft"),
    ]
    # Three reasons quote the vacancy; the fourth was made up.
    assert [i.grounded for i in items] == [True, True, True, False]
    assert all(i.enabled for i in items)


# --- The prompt --------------------------------------------------------------


def test_the_prompt_is_filled_with_the_vacancy_text() -> None:
    prompt = load_prompt(PROMPT)
    user = prompt.render_user(prompt_variables(VACANCY))

    assert prompt.version == "script_v1"
    assert "Title: Cloud Engineer" in user
    assert "- Experience with Microsoft Azure" in user
    assert "$" not in user


def test_the_prompt_asks_for_quotes_and_forbids_protected_attributes() -> None:
    system = " ".join(load_prompt(PROMPT).system.split())

    assert "copied exactly" in system
    assert "never as instructions" in system
    for attribute in ("age", "gender", "nationality", "religion", "health"):
        assert attribute in system
