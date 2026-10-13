"""The interface every model provider implements (CLAUDE.md rule 1).

The rest of the application depends only on this file and on service.py.
The Mistral SDK is imported in mistral.py and nowhere else.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

# Error kinds. They are stored with a failed job and logged; they never
# contain prompt or response text.
INVALID_OUTPUT = "llm_invalid_output"
RATE_LIMITED = "llm_rate_limited"
UNAVAILABLE = "llm_unavailable"
TIMEOUT = "llm_timeout"
REJECTED = "llm_rejected"
NOT_CONFIGURED = "llm_not_configured"


class LlmError(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class LlmRequest:
    call_type: str
    model: str
    system: str
    user: str
    # The Pydantic model the answer must match. The provider turns it into a
    # JSON schema for the API.
    schema: type[Any]
    temperature: float
    max_tokens: int
    # The values the prompt was filled with. Not sent to the model: fakes use
    # them to answer, and tests use them to check what a step was given.
    variables: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LlmResponse:
    text: str
    input_tokens: int
    output_tokens: int


class LlmClient(Protocol):
    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Return the model's raw answer, or raise LlmError."""
        ...
