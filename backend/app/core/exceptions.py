"""Application exceptions and the handlers that render the standard error envelope.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "details": [...]}}
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base application error. Subclasses set status_code/code defaults."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Any | None = None,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        self.message = message or self.__doc__ or "Error"
        self.details = details
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        super().__init__(self.message)


class NotFoundError(AppError):
    """Resource not found."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    """The request conflicts with the current state (e.g. duplicate key)."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class AuthenticationError(AppError):
    """Authentication failed or credentials are missing/invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "authentication_error"


class PermissionDeniedError(AppError):
    """The authenticated user lacks the required permission."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class BusinessRuleError(AppError):
    """A domain/business rule was violated (e.g. insufficient stock)."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "business_rule"


def _envelope(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        # jsonable_encoder so non-JSON-native values in details (e.g. Decimal) don't
        # crash JSONResponse's bare json.dumps.
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(_envelope(exc.code, exc.message, exc.details)),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # exc.errors() carries the offending input + constraint context, which for a
        # Decimal-bounded field (e.g. service_level) contains Decimal objects; encode
        # them so the 422 renders instead of crashing into a 500.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder(
                _envelope("validation_error", "Request validation failed", exc.errors())
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope("http_error", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred"),
        )
