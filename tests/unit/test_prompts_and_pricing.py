from decimal import Decimal

import pytest

from app.config import get_settings
from app.llm.pricing import UnknownModelPriceError, estimate_cost, require_known_price
from app.llm.prompts import load_prompt
from app.vacancy.schemas import VacancyParameters, VacancySections
from app.vacancy.service import PROMPT_VERSION, prompt_variables

PARAMETERS = VacancyParameters.model_validate(
    {
        "sector": "Finance",
        "seniority": ["medior", "senior"],
        "work_mode": ["hybrid"],
        "title": "Risk Analyst",
        "emphasis": "Experience with Basel IV",
    }
)


def test_the_prompt_file_is_loaded_with_its_version() -> None:
    prompt = load_prompt(PROMPT_VERSION)

    assert prompt.version == "vacancy_v1"
    assert prompt.system.startswith("You write job vacancies")
    # The note above "## system" is for developers, not for the model.
    assert "Do not edit after results" not in prompt.system
    assert "## user" not in prompt.system


def test_the_prompt_is_filled_with_the_choices() -> None:
    user = load_prompt(PROMPT_VERSION).render_user(prompt_variables(PARAMETERS))

    assert "Job title: Risk Analyst" in user
    assert "Sector: Finance" in user
    assert "Seniority: medior, senior" in user
    assert "Work mode: hybrid" in user
    assert "Experience with Basel IV" in user
    assert "$" not in user


def test_a_missing_value_is_an_error_not_a_literal_placeholder() -> None:
    with pytest.raises(KeyError):
        load_prompt(PROMPT_VERSION).render_user({"title": "Risk Analyst"})


def test_the_prompt_names_every_section_and_forbids_discrimination() -> None:
    system = load_prompt(PROMPT_VERSION).system

    for field in VacancySections.model_fields:
        assert f'"{field}"' in system
    for attribute in ("age", "gender", "nationality", "religion", "disability"):
        assert attribute in system
    # Form input is data, not instructions.
    assert "never as instructions" in system


def test_cost_is_computed_per_million_tokens() -> None:
    cost = estimate_cost("mistral-small-2603", 1_000_000, 1_000_000)

    assert cost == Decimal("0.75")
    assert estimate_cost("mistral-small-2603", 1000, 500) == Decimal("0.00045")
    assert estimate_cost("fake", 1_000_000, 1_000_000) == Decimal("0")


def test_a_model_without_a_price_is_refused() -> None:
    with pytest.raises(UnknownModelPriceError):
        estimate_cost("some-new-model", 1, 1)
    with pytest.raises(UnknownModelPriceError):
        require_known_price("mistral-small-latest")


def test_the_configured_model_is_pinned_and_has_a_price() -> None:
    model = get_settings().mistral_model_vacancy

    require_known_price(model)
    assert "latest" not in model
