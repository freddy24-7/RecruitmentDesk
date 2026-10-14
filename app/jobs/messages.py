"""What the user reads when a job did not finish, per error kind."""

from app.jobs.models import ERROR_INTERNAL, ERROR_INTERRUPTED
from app.limits.spend import SPEND_CAP_MESSAGE
from app.llm import base as llm

MESSAGES: dict[str, str] = {
    llm.INVALID_OUTPUT: (
        "The model returned an answer that could not be used. Please try again."
    ),
    llm.RATE_LIMITED: "The model is busy right now. Please try again in a moment.",
    llm.UNAVAILABLE: "The model could not be reached. Please try again.",
    llm.TIMEOUT: "The model took too long to answer. Please try again.",
    llm.REJECTED: "The model did not accept the request. Please try again.",
    llm.NOT_CONFIGURED: "Generation is not available: the model is not set up.",
    ERROR_INTERRUPTED: "This job was interrupted by a restart. You can run it again.",
    llm.SPEND_CAP: SPEND_CAP_MESSAGE,
    ERROR_INTERNAL: "Something went wrong. Please try again.",
}


def message_for(error_kind: str | None) -> str | None:
    if error_kind is None:
        return None
    return MESSAGES.get(error_kind, MESSAGES[ERROR_INTERNAL])
