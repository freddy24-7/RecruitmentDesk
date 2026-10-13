"""One error shape for the whole API: `{"error": kind, "message": text}`."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        kind: str,
        message: str,
        *,
        extra: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(kind)
        self.status_code = status_code
        self.kind = kind
        self.message = message
        self.extra = extra or {}
        self.headers = headers


async def _handle_api_error(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ApiError):
        raise error
    return JSONResponse(
        status_code=error.status_code,
        content={"error": error.kind, "message": error.message, **error.extra},
        headers=error.headers,
    )


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
