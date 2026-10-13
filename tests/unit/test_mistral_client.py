"""The Mistral provider, with the SDK call replaced by a stub.

This checks what we send and how answers and errors are translated. It does
not prove that the real API accepts the request: that needs a real call
(tests marked `mistral`, run only on request).
"""

from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from mistralai.client.errors import SDKError

from app.llm.base import (
    NOT_CONFIGURED,
    RATE_LIMITED,
    REJECTED,
    TIMEOUT,
    UNAVAILABLE,
    LlmError,
    LlmRequest,
)
from app.llm.mistral import MistralLlm, error_kind_for_status
from app.vacancy.schemas import VacancySections

REQUEST = LlmRequest(
    call_type="vacancy",
    model="mistral-small-2603",
    system="You write vacancies.",
    user="Write one.",
    schema=VacancySections,
    temperature=0.7,
    max_tokens=2000,
)


def llm_with(result: Any) -> tuple[MistralLlm, list[dict[str, Any]]]:
    """A MistralLlm whose SDK call returns `result`, or raises it."""
    llm = MistralLlm(api_key="fake-key-for-tests", timeout_seconds=60)
    calls: list[dict[str, Any]] = []

    async def complete_async(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    llm._client.chat.complete_async = complete_async  # type: ignore[method-assign]
    return llm, calls


def answer(content: Any) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=340),
    )


async def test_request_uses_the_pinned_model_and_a_strict_json_schema() -> None:
    llm, calls = llm_with(answer('{"ok": true}'))

    await llm.complete(REQUEST)

    [call] = calls
    assert call["model"] == "mistral-small-2603"
    assert call["temperature"] == 0.7
    assert call["max_tokens"] == 2000
    assert [(m.role, m.content) for m in call["messages"]] == [
        ("system", "You write vacancies."),
        ("user", "Write one."),
    ]
    response_format = call["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert set(schema["required"]) == set(VacancySections.model_fields)
    assert schema["additionalProperties"] is False


async def test_answer_text_and_token_counts_are_returned() -> None:
    llm, _ = llm_with(answer('{"ok": true}'))

    response = await llm.complete(REQUEST)

    assert response.text == '{"ok": true}'
    assert (response.input_tokens, response.output_tokens) == (120, 340)


@pytest.mark.parametrize("content", [None, [{"type": "text", "text": "x"}]])
async def test_an_answer_without_plain_text_becomes_empty(content: Any) -> None:
    llm, _ = llm_with(answer(content))

    assert (await llm.complete(REQUEST)).text == ""


async def test_no_choices_becomes_empty_text() -> None:
    llm, _ = llm_with(
        SimpleNamespace(
            choices=[], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=0)
        )
    )

    assert (await llm.complete(REQUEST)).text == ""


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, RATE_LIMITED),
        (401, NOT_CONFIGURED),
        (403, NOT_CONFIGURED),
        (500, UNAVAILABLE),
        (503, UNAVAILABLE),
        (400, REJECTED),
        (422, REJECTED),
    ],
)
async def test_http_errors_become_error_kinds(status: int, kind: str) -> None:
    assert error_kind_for_status(status) == kind
    http_response = httpx2.Response(status, text="secret detail from the API")
    llm, _ = llm_with(SDKError("API error occurred", http_response))

    with pytest.raises(LlmError) as raised:
        await llm.complete(REQUEST)

    assert raised.value.kind == kind
    # The error carries a kind only, never the API's text.
    assert "secret detail" not in str(raised.value)


async def test_a_timeout_becomes_the_timeout_kind() -> None:
    llm, _ = llm_with(httpx2.ReadTimeout("timed out"))

    with pytest.raises(LlmError) as raised:
        await llm.complete(REQUEST)

    assert raised.value.kind == TIMEOUT


async def test_a_network_failure_becomes_unavailable() -> None:
    llm, _ = llm_with(httpx2.ConnectError("no route"))

    with pytest.raises(LlmError) as raised:
        await llm.complete(REQUEST)

    assert raised.value.kind == UNAVAILABLE
