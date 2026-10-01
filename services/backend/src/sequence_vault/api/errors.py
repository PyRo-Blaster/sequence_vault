"""Error contract (design section 8): code, message, request_id, details, retryable."""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from sequence_vault.application.errors import (
    ApplicationError,
    Conflict,
    Forbidden,
    InvalidRequest,
    LimitExceeded,
    NotFound,
)

log = logging.getLogger("sequence_vault.api")

STATUS = {NotFound: 404, Forbidden: 403, Conflict: 409, InvalidRequest: 422, LimitExceeded: 413}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retryable, self.details, self.headers = retryable, details, headers


def request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if value is None:
        value = request.state.request_id = uuid.uuid4().hex
    return str(value)


def error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "code": code,
        "message": message,
        "request_id": request_id(request),
        "details": details,
        "retryable": retryable,
    }
    return JSONResponse(body, status_code=status, headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, error: ApplicationError) -> JSONResponse:
        status = next((code for kind, code in STATUS.items() if isinstance(error, kind)), 400)
        return error_response(request, status, error.code, str(error))

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            request,
            error.status,
            error.code,
            error.message,
            retryable=error.retryable,
            details=error.details,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def malformed(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            {"location": [str(part) for part in item["loc"]], "message": item["msg"]}
            for item in error.errors()
        ]
        return error_response(
            request, 400, "malformed_request", "The request is malformed.", details=details
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(error.status_code, "http_error")
        return error_response(request, error.status_code, code, str(error.detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        log.exception("unhandled error in request %s", request_id(request))
        return error_response(
            request, 500, "internal_error", "Something went wrong.", retryable=True
        )
