"""RFC 7807 (application/problem+json) error responses.

Every error the API returns has the same shape, so clients handle one format:
{"type", "title", "status", "detail", "instance"}.
"""

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ProblemError(Exception):
    """Raise from any route or service to return a problem+json response."""

    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail


def problem_response(
    request: Request,
    status: int,
    title: str,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)


def register_error_handlers(app: FastAPI) -> None:
    async def handle_problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(request, exc.status, exc.title, exc.detail)

    async def handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        try:
            title = HTTPStatus(exc.status_code).phrase
        except ValueError:
            title = "Error"
        return problem_response(request, exc.status_code, title, str(exc.detail))

    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Keep only location and message. Pydantic's default output echoes the
        # submitted input, which can contain user data we should not reflect.
        errors = [
            {"loc": [str(part) for part in err["loc"]], "msg": err["msg"]} for err in exc.errors()
        ]
        return problem_response(
            request, 422, "Validation failed", "The request is invalid.", errors=errors
        )

    app.add_exception_handler(ProblemError, handle_problem)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, handle_http)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation)  # type: ignore[arg-type]
