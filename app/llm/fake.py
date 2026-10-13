"""A stand-in for the model, behind the same interface.

Used by every test, so the pipeline runs in seconds without the network, and
in development with LLM_PROVIDER=fake, so the UI can be built without cost.
"""

import asyncio
import json
from collections.abc import Callable

from app.llm.base import NOT_CONFIGURED, LlmError, LlmRequest, LlmResponse

Responder = Callable[[LlmRequest], str]

FAKE_NOTE = "[Fake model output]"


def fake_vacancy(request: LlmRequest) -> str:
    v = request.variables
    title = v.get("title", "Example role")
    company = v.get("company") or "Northwind Example BV"
    return json.dumps(
        {
            "title": title,
            "company_intro": (
                f"{FAKE_NOTE} {company} is a fictional organisation in the "
                f"{v.get('sector', 'example')} sector."
            ),
            "role_summary": (
                f"As {title} ({v.get('seniority', 'medior')}) you work on "
                "example projects together with a small team."
            ),
            "responsibilities": [
                "Deliver the example work that belongs to this role",
                "Work together with colleagues and stakeholders",
                "Improve the way the team works",
            ],
            "required_qualifications": [
                "3 years of experience in a comparable role",
                "Experience with Microsoft Azure",
                "Good written and spoken English",
            ],
            "nice_to_haves": ["Experience in a regulated sector"],
            "what_we_offer": [
                "A competitive salary",
                "Room to learn and to grow",
            ],
            "location_and_work_mode": (
                f"Utrecht, the Netherlands. Work mode: {v.get('work_mode', 'hybrid')}."
            ),
        }
    )


DEFAULT_RESPONDERS: dict[str, Responder] = {"vacancy": fake_vacancy}


class FakeLlm:
    """Answers from `responders`, per call type, and remembers every request.

    A responder may be replaced by a list of raw answers, returned in order,
    or by an exception to raise.
    """

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.responders: dict[str, Responder] = dict(DEFAULT_RESPONDERS)
        self.scripted: dict[str, list[str | Exception]] = {}
        self.requests: list[LlmRequest] = []
        self.delay_seconds = delay_seconds
        # Tests set this to hold a call open until they release it.
        self.gate: asyncio.Event | None = None

    def script(self, call_type: str, *answers: str | Exception) -> None:
        self.scripted.setdefault(call_type, []).extend(answers)

    async def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.gate is not None:
            await self.gate.wait()

        queued = self.scripted.get(request.call_type)
        if queued:
            answer = queued.pop(0)
            if isinstance(answer, Exception):
                raise answer
            text = answer
        else:
            text = self.responders[request.call_type](request)

        return LlmResponse(
            text=text,
            input_tokens=(len(request.system) + len(request.user)) // 4,
            output_tokens=len(text) // 4,
        )


class UnconfiguredLlm:
    """Used when no API key is set: every call fails with a clear error kind."""

    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise LlmError(NOT_CONFIGURED)
