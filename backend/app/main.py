"""FastAPI application factory."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import auth_policy
from app.core.config import DEFAULT_JWT_SECRET, settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the daily intelligence scheduler when enabled; stop it on shutdown.
    Off by default, so this is a no-op in tests and normal runs."""
    task: asyncio.Task | None = None
    stop: asyncio.Event | None = None
    if settings.intel_scheduler_enabled:
        from app.db.session import AsyncSessionLocal
        from app.intelligence.scheduler import IntelligenceScheduler

        stop = asyncio.Event()
        scheduler = IntelligenceScheduler(AsyncSessionLocal, settings)
        task = asyncio.create_task(scheduler.loop(stop))
    try:
        yield
    finally:
        if task and stop:
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _validate_jwt_secret() -> None:
    """Fail fast in production on a weak/default JWT secret; warn otherwise."""
    problems = auth_policy.secret_problems(
        settings.jwt_secret_key,
        environment=settings.environment,
        known_default=DEFAULT_JWT_SECRET,
    )
    if not problems:
        return
    detail = "; ".join(problems)
    if settings.is_production:
        raise RuntimeError(
            f"Insecure JWT secret ({detail}). Set a strong JWT_SECRET_KEY before "
            "running in production."
        )
    logger.warning("insecure_jwt_secret", problems=problems)


def _validate_freightos() -> None:
    """If Freightos is enabled, both credentials must be present. Fail fast in
    production; warn otherwise. Logs only the missing field NAMES, never values."""
    from app.intelligence.sources.freightos import credential_problems

    missing = credential_problems(
        enabled=settings.freightos_enabled,
        api_key=settings.freightos_api_key,
        api_secret=settings.freightos_api_secret,
    )
    if not missing:
        return
    detail = ", ".join(missing)
    if settings.is_production:
        raise RuntimeError(
            f"Freightos is enabled but missing credentials: {detail}. Set them, "
            "or set FREIGHTOS_ENABLED=false."
        )
    logger.warning("freightos_credentials_missing", missing=missing)


def create_app() -> FastAPI:
    configure_logging(level=settings.log_level, as_json=settings.log_json)
    _validate_jwt_secret()
    _validate_freightos()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Edge protection: rate limiting + security headers (+ optional HTTPS redirect).
    from app.core.middleware import SecurityMiddleware
    from app.core.ratelimit import InMemoryRateLimiter, RateLimitRule
    from app.core.security_headers import build_security_headers

    app.add_middleware(
        SecurityMiddleware,
        limiter=InMemoryRateLimiter(),
        general_rule=RateLimitRule(limit=settings.rate_limit_per_minute, window_seconds=60),
        auth_rule=RateLimitRule(limit=settings.auth_rate_limit_per_minute, window_seconds=60),
        auth_prefix=f"{settings.api_v1_prefix}/auth",
        enabled=settings.rate_limit_enabled,
        trust_proxy=settings.trust_proxy_headers,
        headers=(
            build_security_headers(
                hsts_enabled=settings.hsts_enabled, hsts_max_age=settings.hsts_max_age
            )
            if settings.security_headers_enabled
            else {}
        ),
    )

    if settings.https_redirect:
        from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

        app.add_middleware(HTTPSRedirectMiddleware)

    register_exception_handlers(app)

    # Routers (imported here to keep import side effects out of module import).
    from app.api.v1.router import api_router

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    logger.info("app_started", app=settings.app_name, env=settings.environment)
    return app


app = create_app()
