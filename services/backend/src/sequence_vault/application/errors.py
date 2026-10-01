"""Errors raised by use cases; the API maps each to a status code."""


class ApplicationError(Exception):
    code = "error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class NotFound(ApplicationError):
    """Missing, or not visible to the caller. Never distinguish the two."""

    code = "not_found"


class Forbidden(ApplicationError):
    code = "forbidden"


class Conflict(ApplicationError):
    """Revision or business conflict (HTTP 409)."""

    code = "conflict"


class InvalidRequest(ApplicationError):
    """Well-formed request with unacceptable content (HTTP 422)."""

    code = "invalid_request"


class LimitExceeded(ApplicationError):
    """A configured size or count limit was exceeded (HTTP 413)."""

    code = "limit_exceeded"
