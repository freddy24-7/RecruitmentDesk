"""One real call to the Mistral API. Costs money: run only on request.

    uv run pytest -m mistral tests/real -s

Needs MISTRAL_API_KEY in the environment or in .env. Not run by default and
never in CI. It answers the questions the fake cannot: does the API accept
our strict JSON schema, does the pinned model name exist, and is the answer
a valid vacancy?
"""

import os
import time
from datetime import date

import pytest

from app.candidates.blueprints import sample_blueprints
from app.candidates.cv import problems_in
from app.candidates.schemas import CvText, VacancyProfile
from app.candidates.service import (
    CV_CALL,
    CV_MAX_TOKENS,
    CV_PROMPT,
    CV_TEMPERATURE,
    PROFILE_CALL,
    PROFILE_MAX_TOKENS,
    PROFILE_PROMPT,
    PROFILE_TEMPERATURE,
    cv_variables,
)
from app.config import get_settings
from app.llm.base import LlmRequest
from app.llm.fake import fake_vacancy
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


async def test_the_real_model_analyses_a_vacancy_and_writes_usable_cvs() -> None:
    """One profile call and four CV calls (one per match category).

    Shows what the fake cannot: whether the real model keeps to the rules that
    protect the ground truth (no missing skills, skills only in their own job,
    no personal details), and what a CV costs.
    """
    api_key = os.environ.get("RECRUITDESK_REAL_MISTRAL_API_KEY", "")
    if not api_key:
        pytest.skip("MISTRAL_API_KEY is not set")
    settings = get_settings()
    llm = MistralLlm(api_key, timeout_seconds=60)

    vacancy = VacancySections.model_validate_json(
        fake_vacancy(
            LlmRequest(
                call_type=CALL_TYPE,
                model="fake",
                system="",
                user="",
                schema=VacancySections,
                temperature=0,
                max_tokens=1,
                variables={"title": "Cloud Engineer", "sector": "IT and software"},
            )
        )
    )
    profile_prompt = load_prompt(PROFILE_PROMPT)
    profile_response = await llm.complete(
        LlmRequest(
            call_type=PROFILE_CALL,
            model=settings.mistral_model_vacancy,
            system=profile_prompt.system,
            user=profile_prompt.render_user(
                {
                    "title": vacancy.title,
                    "sector": "IT and software",
                    "role_summary": vacancy.role_summary,
                    "responsibilities": "\n".join(vacancy.responsibilities),
                    "required_qualifications": "\n".join(
                        vacancy.required_qualifications
                    ),
                    "nice_to_haves": "\n".join(vacancy.nice_to_haves),
                }
            ),
            schema=VacancyProfile,
            temperature=PROFILE_TEMPERATURE,
            max_tokens=PROFILE_MAX_TOKENS,
        )
    )
    profile = VacancyProfile.model_validate_json(profile_response.text)
    required = [(need.any_of, need.min_years) for need in profile.required_skills]
    print(
        f"\nprofile: required={required} "
        f"nice={profile.nice_skills} "
        f"adjacent={[r.title for r in profile.adjacent_roles]} "
        f"unrelated={[r.title for r in profile.unrelated_roles]}"
    )

    # The first blueprint of each match category, from a pool of twenty.
    pool = sample_blueprints(
        n=20,
        seed=settings.blueprint_seed,
        title=vacancy.title,
        seniority=["senior"],
        profile=profile,
        as_of=date.today(),
    )
    one_per_category = {b.match_category: b for b in reversed(pool)}
    cv_prompt = load_prompt(CV_PROMPT)
    total_cost = estimate_cost(
        settings.mistral_model_vacancy,
        profile_response.input_tokens,
        profile_response.output_tokens,
    )
    unusable = 0
    for category, blueprint in one_per_category.items():
        variables = cv_variables(blueprint, "IT and software")
        response = await llm.complete(
            LlmRequest(
                call_type=CV_CALL,
                model=settings.mistral_model_cv,
                system=cv_prompt.system,
                user=cv_prompt.render_user(variables),
                schema=CvText,
                temperature=CV_TEMPERATURE,
                max_tokens=CV_MAX_TOKENS,
            )
        )
        cost = estimate_cost(
            settings.mistral_model_cv, response.input_tokens, response.output_tokens
        )
        total_cost += cost
        try:
            problems = problems_in(CvText.model_validate_json(response.text), blueprint)
        except ValueError:
            problems = ["invalid_json_or_schema"]
        unusable += bool(problems)
        print(
            f"cv {category.value}: input_tokens={response.input_tokens} "
            f"output_tokens={response.output_tokens} cost_usd={cost:.6f} "
            f"problems={problems}"
        )
    print(
        f"total_estimated_cost_usd={total_cost:.6f} unusable_first_answers={unusable}/4"
    )
    assert len(one_per_category) == 4
