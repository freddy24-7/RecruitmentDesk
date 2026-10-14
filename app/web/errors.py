"""One error shape for the whole API: `{"error": kind, "message": text}`."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
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


def add_body_limit(app: FastAPI, max_bytes: int) -> None:
    """Refuse requests whose body is larger than `max_bytes` (PRD section 11).

    The size is taken from the Content-Length header. A request without one
    is read in full by FastAPI only when a route needs the body, and every
    route that does validates its input with limits on length.
    """

    @app.middleware("http")
    async def limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length")
        if length is not None and (not length.isdigit() or int(length) > max_bytes):
            return JSONResponse(
                status_code=413,
                content={"error": "too_large", "message": "This request is too large."},
            )
        return await call_next(request)
