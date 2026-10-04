"""Identity from the OIDC proxy (ADR 0006) and request hygiene middleware."""

import hmac
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request, Response

from sequence_vault.api.errors import ApiError, error_response
from sequence_vault.application.authorization import Actor
from sequence_vault.application.queries import ReadModel
from sequence_vault.settings import Settings

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "sequence-vault"


@dataclass(frozen=True, slots=True)
class Principal:
    actor: Actor
    display_name: str


class Authenticator:
    def __init__(self, settings: Settings, read: ReadModel) -> None:
        self.settings = settings
        self.read = read

    def subject(self, request: Request) -> str | None:
        if self.settings.is_development and self.settings.dev_login:
            dev_user = request.headers.get("X-Dev-User")
            if dev_user:
                return dev_user.strip()
        subject = request.headers.get(self.settings.trusted_identity_header)
        if not subject:
            return None
        secret = self.settings.proxy_secret
        presented = request.headers.get("X-Proxy-Secret", "")
        if secret is None or not hmac.compare_digest(presented.encode(), secret.encode()):
            return None
        return subject.strip()

    def __call__(self, request: Request) -> Principal:
        subject = self.subject(request)
        if not subject:
            raise ApiError(401, "unauthenticated", "Sign in to continue.")
        user = self.read.user_by_subject(subject)
        if user is None:
            raise ApiError(
                403,
                "user_not_provisioned",
                "Your account has not been added to Sequence Vault yet.",
            )
        return Principal(Actor(user["user_id"], user["tenant_id"]), user["display_name"])


class RateLimiter:
    """Per-subject token bucket for write requests (per process; the proxy may add more)."""

    def __init__(self, per_minute: int = 600) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1:
                self.buckets[key] = (tokens, now)
                return False
            self.buckets[key] = (tokens - 1, now)
            return True


Next = Callable[[Request], Awaitable[Response]]


def guard(
    authenticator: Authenticator, limiter: RateLimiter
) -> Callable[[Request, Next], Awaitable[Response]]:
    async def middleware(request: Request, call_next: Next) -> Response:
        if request.method in UNSAFE_METHODS and request.url.path.startswith("/v1/"):
            if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                return error_response(
                    request,
                    403,
                    "csrf_header_missing",
                    f"State-changing requests need {CSRF_HEADER}: {CSRF_VALUE}.",
                )
            key = authenticator.subject(request) or (request.client.host if request.client else "?")
            if not limiter.allow(key):
                return error_response(
                    request,
                    429,
                    "rate_limited",
                    "Too many requests.",
                    retryable=True,
                    headers={"Retry-After": "1"},
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    return middleware
