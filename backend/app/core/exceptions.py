"""Application level exceptions mapped to consistent API error envelopes."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every expected (non-bug) failure."""

    status_code = 400
    code = "BAD_REQUEST"
    message = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.code = code or self.__class__.code
        self.status_code = status_code or self.__class__.status_code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "The requested resource could not be found."


class ValidationError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    message = "The submitted data is invalid."


class AuthenticationError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"
    message = "Authentication is required to access this resource."


class PermissionDeniedError(AppError):
    status_code = 403
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"
    message = "The resource is in a conflicting state."


class InvalidStateTransitionError(ConflictError):
    code = "INVALID_STATE_TRANSITION"
    message = "That action is not allowed from the current status."


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests. Please try again shortly."


class ExternalServiceError(AppError):
    status_code = 502
    code = "EXTERNAL_SERVICE_ERROR"
    message = "An external service is currently unavailable."


class AINotConfiguredError(AppError):
    status_code = 503
    code = "AI_NOT_CONFIGURED"
    message = (
        "The AI assistant is not configured on this deployment. "
        "Set NVIDIA_API_KEY to enable conversational answers."
    )
