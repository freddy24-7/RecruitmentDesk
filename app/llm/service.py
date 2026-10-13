"""The one door to the model: structured output, validation, usage records.

Every model call in the application goes through `LlmService.generate`.
The answer is JSON that must match a Pydantic schema. Invalid output is
retried once, then fails with a clear error kind (CLAUDE.md rule 2).
"""

import time
import uuid
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.llm.base import INVALID_OUTPUT, LlmClient, LlmError, LlmRequest
from app.llm.fake import FakeLlm, UnconfiguredLlm
from app.llm.pricing import FAKE_MODEL, estimate_cost
from app.llm.prompts import Prompt
from app.llm.usage import OUTCOME_INVALID_OUTPUT, OUTCOME_OK, UsageRecord

log = structlog.get_logger()

MAX_ATTEMPTS = 2  # the first try, plus one retry on invalid output


def build_client(settings: Settings) -> LlmClient:
    if settings.llm_provider == "fake":
        return FakeLlm(delay_seconds=settings.fake_llm_delay_seconds)
    if settings.mistral_api_key is None:
        return UnconfiguredLlm()
    # Imported here, so the SDK is only loaded when it is actually used.
    from app.llm.mistral import MistralLlm

    return MistralLlm(
        api_key=settings.mistral_api_key.get_secret_value(),
        timeout_seconds=settings.llm_timeout_seconds,
    )


class LlmService:
    def __init__(
        self, client: LlmClient, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        self.client = client
        self._sessionmaker = sessionmaker

    def model_name(self, configured: str) -> str:
        """The fake is recorded as `fake`, so its usage is never mistaken for spend."""
        return FAKE_MODEL if isinstance(self.client, FakeLlm) else configured

    async def generate[T: BaseModel](
        self,
        *,
        call_type: str,
        model: str,
        prompt: Prompt,
        variables: dict[str, str],
        schema: type[T],
        temperature: float,
        max_tokens: int,
        workspace_id: uuid.UUID | None,
        job_id: uuid.UUID | None,
    ) -> T:
        model = self.model_name(model)
        request = LlmRequest(
            call_type=call_type,
            model=model,
            system=prompt.system,
            user=prompt.render_user(variables),
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            variables=variables,
        )

        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            response = await self.client.complete(request)
            latency_ms = int((time.monotonic() - started) * 1000)

            try:
                value = schema.model_validate_json(response.text)
            except ValidationError:
                value = None

            await self._record(
                request,
                prompt.version,
                OUTCOME_OK if value is not None else OUTCOME_INVALID_OUTPUT,
                response.input_tokens,
                response.output_tokens,
                latency_ms,
                workspace_id,
                job_id,
            )
            if value is not None:
                return value
            # Log the kind and the attempt, never the model's text.
            log.warning("llm.invalid_output", call_type=call_type, attempt=attempt)

        raise LlmError(INVALID_OUTPUT)

    async def _record(
        self,
        request: LlmRequest,
        prompt_version: str,
        outcome: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        workspace_id: uuid.UUID | None,
        job_id: uuid.UUID | None,
    ) -> None:
        # Its own transaction: the usage is kept even if the job fails later.
        async with self._sessionmaker() as session:
            session.add(
                UsageRecord(
                    workspace_id=workspace_id,
                    job_id=job_id,
                    call_type=request.call_type,
                    model=request.model,
                    prompt_version=prompt_version,
                    outcome=outcome,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    estimated_cost=estimate_cost(
                        request.model, input_tokens, output_tokens
                    ),
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()
        log.info(
            "llm.call",
            call_type=request.call_type,
            model=request.model,
            outcome=outcome,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
