"""Structured output, one retry on invalid output, and usage records (rule 2)."""

import json
from decimal import Decimal

import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.llm.base import (
    INVALID_OUTPUT,
    RATE_LIMITED,
    LlmError,
    LlmRequest,
    LlmResponse,
)
from app.llm.fake import FakeLlm
from app.llm.prompts import Prompt
from app.llm.service import LlmService
from app.llm.usage import UsageRecord


class Answer(BaseModel):
    city: str
    population: int


PROMPT = Prompt(
    version="test_v1", system="Answer in JSON.", user_template="City: $city"
)
VALID = json.dumps({"city": "Utrecht", "population": 370000})


async def ask(service: LlmService) -> Answer:
    return await service.generate(
        call_type="test",
        model="mistral-small-2603",
        prompt=PROMPT,
        variables={"city": "Utrecht"},
        schema=Answer,
        temperature=0.0,
        max_tokens=100,
        workspace_id=None,
        job_id=None,
    )


async def usage(db: AsyncSession) -> list[UsageRecord]:
    return list((await db.scalars(select(UsageRecord).order_by(UsageRecord.id))).all())


@pytest.fixture
def service(llm: FakeLlm) -> LlmService:
    return LlmService(llm, get_sessionmaker())


async def test_a_valid_answer_is_parsed_and_recorded(
    service: LlmService, llm: FakeLlm, db: AsyncSession
) -> None:
    llm.script("test", VALID)

    answer = await ask(service)

    assert answer == Answer(city="Utrecht", population=370000)
    [request] = llm.requests
    assert request.user == "City: Utrecht"
    assert request.system == "Answer in JSON."
    [record] = await usage(db)
    assert (record.call_type, record.outcome, record.prompt_version) == (
        "test",
        "ok",
        "test_v1",
    )
    assert record.input_tokens > 0
    assert record.output_tokens > 0
    assert record.latency_ms >= 0


@pytest.mark.parametrize(
    "bad",
    [
        "Sure! Here is the answer: Utrecht",
        "",
        '{"city": "Utrecht"}',
        '{"city": "Utrecht", "population": "many"}',
        '```json\n{"city": "Utrecht", "population": 1}\n```',
    ],
)
async def test_invalid_output_is_retried_once(
    bad: str, service: LlmService, llm: FakeLlm, db: AsyncSession
) -> None:
    llm.script("test", bad, VALID)

    answer = await ask(service)

    assert answer.city == "Utrecht"
    assert len(llm.requests) == 2
    # Both calls cost money, so both are recorded.
    assert [r.outcome for r in await usage(db)] == ["invalid_output", "ok"]


async def test_invalid_output_twice_fails_with_a_clear_kind(
    service: LlmService, llm: FakeLlm, db: AsyncSession
) -> None:
    llm.script("test", "not json", "still not json", VALID)

    with pytest.raises(LlmError) as raised:
        await ask(service)

    assert raised.value.kind == INVALID_OUTPUT
    # One retry, not more.
    assert len(llm.requests) == 2
    assert [r.outcome for r in await usage(db)] == ["invalid_output", "invalid_output"]


async def test_a_provider_error_is_passed_on_and_not_retried_here(
    service: LlmService, llm: FakeLlm, db: AsyncSession
) -> None:
    llm.script("test", LlmError(RATE_LIMITED), VALID)

    with pytest.raises(LlmError) as raised:
        await ask(service)

    assert raised.value.kind == RATE_LIMITED
    assert len(llm.requests) == 1
    assert await usage(db) == []


async def test_the_fake_is_recorded_as_fake_and_costs_nothing(
    service: LlmService, llm: FakeLlm, db: AsyncSession
) -> None:
    llm.script("test", VALID)

    await ask(service)

    [record] = await usage(db)
    assert record.model == "fake"
    assert record.estimated_cost == Decimal("0")


async def test_cost_is_estimated_from_the_tokens_of_a_priced_model(
    db: AsyncSession,
) -> None:
    class PricedStub:
        async def complete(self, request: LlmRequest) -> LlmResponse:
            return LlmResponse(text=VALID, input_tokens=2000, output_tokens=1000)

    await ask(LlmService(PricedStub(), get_sessionmaker()))

    [record] = await usage(db)
    assert record.model == "mistral-small-2603"
    # 2000 x 0.15 / 1M + 1000 x 0.60 / 1M
    assert record.estimated_cost == Decimal("0.000900")
