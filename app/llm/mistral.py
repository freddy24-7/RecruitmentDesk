"""The Mistral provider. The only module that imports the Mistral SDK."""

import httpx2
from mistralai.client import Mistral
from mistralai.client.errors.mistralerror import MistralError
from mistralai.client.models import SystemMessage, UserMessage
from mistralai.client.utils import BackoffStrategy, RetryConfig
from mistralai.extra import response_format_from_pydantic_model

from app.llm.base import (
    NOT_CONFIGURED,
    RATE_LIMITED,
    REJECTED,
    TIMEOUT,
    UNAVAILABLE,
    LlmError,
    LlmRequest,
    LlmResponse,
)

# The SDK retries 429 and 5xx answers itself, with exponential backoff:
# first wait 1 s, at most 20 s between tries, give up after 60 s in total.
RETRIES = RetryConfig(
    "backoff",
    BackoffStrategy(
        initial_interval=1_000,
        max_interval=20_000,
        exponent=2.0,
        max_elapsed_time=60_000,
    ),
    retry_connection_errors=True,
)


def error_kind_for_status(status_code: int) -> str:
    if status_code == 429:
        return RATE_LIMITED
    if status_code in (401, 403):
        return NOT_CONFIGURED
    if status_code >= 500:
        return UNAVAILABLE
    return REJECTED


class MistralLlm:
    def __init__(self, api_key: str, timeout_seconds: int) -> None:
        self._client = Mistral(
            api_key=api_key,
            retry_config=RETRIES,
            timeout_ms=timeout_seconds * 1000,
        )

    async def complete(self, request: LlmRequest) -> LlmResponse:
        messages: list[SystemMessage | UserMessage] = [
            SystemMessage(content=request.system),
            UserMessage(content=request.user),
        ]
        try:
            response = await self._client.chat.complete_async(
                model=request.model,
                messages=messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                # A strict JSON schema: the API constrains the answer to it.
                response_format=response_format_from_pydantic_model(request.schema),
            )
        except MistralError as error:
            raise LlmError(error_kind_for_status(error.status_code)) from error
        except httpx2.TimeoutException as error:
            raise LlmError(TIMEOUT) from error
        except httpx2.RequestError as error:
            raise LlmError(UNAVAILABLE) from error

        message = response.choices[0].message if response.choices else None
        content = message.content if message else None
        return LlmResponse(
            # Anything but plain text fails validation later, as invalid output.
            text=content if isinstance(content, str) else "",
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
        )
