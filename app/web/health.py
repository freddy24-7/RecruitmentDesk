"""Health check for the host and uptime monitors."""

from fastapi import APIRouter

router = APIRouter()


# GET and HEAD: uptime monitors often send HEAD. The handler does no work on
# purpose (no database, no model call), so a monitor can never cost money.
@router.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
