"""One real call to the Mistral API. Costs money: run only on request.

    uv run pytest -m mistral tests/real -s

Needs MISTRAL_API_KEY in the environment or in .env. Not run by default and
never in CI. It answers the questions the fake cannot: does the API accept
our strict JSON schema, does the pinned model name exist, and is the answer
a valid vacancy?
"""

import os
import time

import pytest

from app.config import get_settings
from app.llm.base import LlmRequest
from app.llm.mistral import MistralLlm
from app.llm.pricing import estimate_cost
from app.llm.prompts import load_prompt
from app.vacancy.guardrails import find_flags
from app.vacancy.schemas import VacancyParameters, VacancySections
from app.vacancy.service import (
    CALL_TYPE,
    MAX_TOKENS,
    PROMPT_VERSION,
    TEMPERATURE,
    prompt_variables,
)

pytestmark = pytest.mark.mistral


async def test_the_real_model_returns_a_valid_vacancy() -> None:
    api_key = os.environ.get("RECRUITDESK_REAL_MISTRAL_API_KEY", "")
    if not api_key:
        pytest.skip("MISTRAL_API_KEY is not set")
    model = get_settings().mistral_model_vacancy
    parameters = VacancyParameters.model_validate(
        {
            "sector": "IT and software",
            "seniority": ["senior"],
            "work_mode": ["hybrid"],
            "title": "Cloud Engineer",
        }
    )
    prompt = load_prompt(PROMPT_VERSION)
    variables = prompt_variables(parameters)

    started = time.monotonic()
    response = await MistralLlm(api_key, timeout_seconds=60).complete(
        LlmRequest(
            call_type=CALL_TYPE,
            model=model,
            system=prompt.system,
            user=prompt.render_user(variables),
            schema=VacancySections,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            variables=variables,
        )
    )
    seconds = time.monotonic() - started

    sections = VacancySections.model_validate_json(response.text)
    cost = estimate_cost(model, response.input_tokens, response.output_tokens)
    print(
        f"\nmodel={model} input_tokens={response.input_tokens} "
        f"output_tokens={response.output_tokens} seconds={seconds:.1f} "
        f"estimated_cost_usd={cost:.6f} flags={len(find_flags(sections))}"
    )
    assert sections.title
    assert len(sections.responsibilities) >= 3
    assert len(sections.required_qualifications) >= 3
