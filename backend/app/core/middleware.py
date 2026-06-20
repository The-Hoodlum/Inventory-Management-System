"""Edge security middleware: per-client rate limiting (stricter on /auth) and
baseline security headers on every response.

The rate-limit decision is delegated to ``app.core.ratelimit`` (unit-tested);
this middleware handles request plumbing only. Behind a trusted proxy, set
``trust_proxy_headers`` so the client IP is taken from ``X-Forwarded-For``.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.ratelimit import InMemoryRateLimiter, RateLimitRule


def client_ip(request: Request, *, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        limiter: InMemoryRateLimiter,
        general_rule: RateLimitRule,
        auth_rule: RateLimitRule,
        auth_prefix: str,
        enabled: bool,
        trust_proxy: bool,
        headers: dict[str, str],
    ) -> None:
        super().__init__(app)
        self.limiter = limiter
        self.general_rule = general_rule
        self.auth_rule = auth_rule
        self.auth_prefix = auth_prefix
        self.enabled = enabled
        self.trust_proxy = trust_proxy
        self.headers = headers
        self._hits = 0
        self._max_window = max(general_rule.window_seconds, auth_rule.window_seconds)

    def _apply_headers(self, response: Response) -> None:
        for key, value in self.headers.items():
            response.headers.setdefault(key, value)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Never rate-limit CORS preflight.
        if self.enabled and request.method != "OPTIONS":
            is_auth = request.url.path.startswith(self.auth_prefix)
            rule = self.auth_rule if is_auth else self.general_rule
            key = f"{'auth' if is_auth else 'gen'}:{client_ip(request, trust_proxy=self.trust_proxy)}"
            now = time.monotonic()
            result = self.limiter.hit(key, rule, now)

            # Opportunistically bound memory.
            self._hits += 1
            if self._hits % 1000 == 0:
                self.limiter.prune(now, max_window_seconds=self._max_window)

            if not result.allowed:
                resp = JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate_limited",
                            "message": "Too many requests. Please retry shortly.",
                        }
                    },
                )
                resp.headers["Retry-After"] = str(result.retry_after)
                resp.headers["X-RateLimit-Limit"] = str(rule.limit)
                resp.headers["X-RateLimit-Remaining"] = "0"
                self._apply_headers(resp)
                return resp

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(rule.limit)
            response.headers["X-RateLimit-Remaining"] = str(result.remaining)
            self._apply_headers(response)
            return response

        response = await call_next(request)
        self._apply_headers(response)
        return response
