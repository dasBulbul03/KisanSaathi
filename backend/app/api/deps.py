"""Shared FastAPI dependencies: request context, authentication and RBAC.

Every router composes these helpers so authentication, permission checks and
pagination behave identically across the whole API surface.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.enums import UserRole, UserStatus
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.rbac import ROLE_PERMISSIONS
from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models import User
from app.schemas.common import MAX_PAGE_SIZE, PageParams
from app.services.auth_service import AuthService

# ``auto_error`` is off so a missing header produces our own error envelope
# rather than FastAPI's default 403 shape.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[Session, Depends(get_db)]


# --------------------------------------------------------------- request ctx
@dataclass(frozen=True, slots=True)
class RequestContext:
    """Per-request metadata captured for audit logging and rate limiting."""

    request_id: str
    ip_address: str | None = None
    user_agent: str | None = None


def get_request_context(request: Request) -> RequestContext:
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    forwarded = request.headers.get("x-forwarded-for")
    client_ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    return RequestContext(
        request_id=request_id,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent"),
    )


RequestCtx = Annotated[RequestContext, Depends(get_request_context)]


# ------------------------------------------------------------------ the user
def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
) -> User:
    """Resolve the authenticated user from the bearer token."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError(
            "Provide an access token in the Authorization: Bearer <token> header."
        )
    try:
        decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise AuthenticationError(f"Invalid or expired access token: {exc}") from exc
    user = AuthService(session).authenticate_token(credentials.credentials)
    if user.status is UserStatus.SUSPENDED:
        raise PermissionDeniedError(
            "This account is suspended. Contact support to restore access.",
            code="ACCOUNT_SUSPENDED",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DbSession,
) -> User | None:
    """Resolve the user when a token is present, otherwise return ``None``.

    Used by read-only marketplace endpoints so listings work for signed-out
    visitors while still personalising results for signed-in ones.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        decode_token(credentials.credentials, expected_type="access")
    except TokenError:
        return None
    return AuthService(session).authenticate_token(credentials.credentials)


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


# ---------------------------------------------------------------------- RBAC
def require_permissions(*permissions: str) -> Callable[..., User]:
    """Dependency factory enforcing that the caller holds *all* permissions.

    Administrators implicitly hold every permission so new endpoints do not
    need to be added to the admin grant list.
    """
    required = set(permissions)

    def _dependency(user: CurrentUser) -> User:
        if user.role is UserRole.ADMIN:
            return user
        held = set(ROLE_PERMISSIONS.get(user.role, []))
        missing = required - held
        if missing:
            raise PermissionDeniedError(
                "Your role does not permit this action.",
                code="INSUFFICIENT_PERMISSIONS",
                details={"required": sorted(required), "missing": sorted(missing)},
            )
        return user

    return _dependency


def require_any_permission(*permissions: str) -> Callable[..., User]:
    """Dependency factory enforcing at least one of *permissions*."""
    required = set(permissions)

    def _dependency(user: CurrentUser) -> User:
        if user.role is UserRole.ADMIN:
            return user
        if required & set(ROLE_PERMISSIONS.get(user.role, [])):
            return user
        raise PermissionDeniedError(
            "Your role does not permit this action.",
            code="INSUFFICIENT_PERMISSIONS",
            details={"required_any": sorted(required)},
        )

    return _dependency


def require_roles(*roles: UserRole) -> Callable[..., User]:
    """Dependency factory restricting an endpoint to specific roles."""
    allowed = set(roles)

    def _dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError(
                f"This action is restricted to: {', '.join(sorted(r.value for r in allowed))}.",
                code="ROLE_NOT_ALLOWED",
                details={"required_roles": sorted(r.value for r in allowed)},
            )
        return user

    return _dependency


CurrentSeller = Annotated[User, Depends(require_roles(UserRole.FARMER, UserRole.FPO))]
CurrentBuyer = Annotated[User, Depends(require_roles(UserRole.BUYER))]
CurrentAdmin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


# --------------------------------------------------------------- pagination
def get_page_params(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Items per page")
    ] = PageParams.model_fields["page_size"].default,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(get_page_params)]
