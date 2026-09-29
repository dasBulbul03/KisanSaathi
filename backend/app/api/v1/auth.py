"""Authentication and self-service account endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession, RequestCtx
from app.core.rbac import ROLE_PERMISSIONS
from app.models import Role
from app.repositories.users import RoleRepository
from app.schemas.user import (
    BuyerProfileOut,
    FarmerProfileOut,
    FPOProfileOut,
    LoginRequest,
    PasswordChangeRequest,
    ProfileOut,
    RefreshRequest,
    RegisterRequest,
    RoleOut,
    TokenResponse,
    UserSummary,
    UserUpdateSelf,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _profile(user, permissions: list[str]) -> ProfileOut:
    """Assemble the caller profile plus the flat permission list.

    The frontend uses ``permissions`` to decide which actions to render, so it
    must mirror ``ROLE_PERMISSIONS`` exactly rather than being a second source
    of truth in the client.
    """
    return ProfileOut(
        user=UserSummary.model_validate(user),
        farmer=FarmerProfileOut.model_validate(user.farmer_profile)
        if user.farmer_profile
        else None,
        fpo=FPOProfileOut.model_validate(user.fpo_profile) if user.fpo_profile else None,
        buyer=BuyerProfileOut.model_validate(user.buyer_profile) if user.buyer_profile else None,
        permissions=permissions,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
def register(payload: RegisterRequest, session: DbSession) -> TokenResponse:
    """Create an account and return tokens immediately (no email round-trip).

    ``role`` selects the onboarding path: FARMER and FPO get a seller profile,
    BUYER gets a buyer profile. ADMIN / inspector / logistics accounts are
    created by an existing administrator, never self-served.
    """
    user, tokens = AuthService(session).register(payload)
    return tokens


@router.post("/login", response_model=TokenResponse, summary="Log in")
def login(payload: LoginRequest, session: DbSession, ctx: RequestCtx) -> TokenResponse:
    """Exchange a phone number or email plus password for an access/refresh pair."""
    _, tokens = AuthService(session).login(
        payload,
        user_agent=ctx.user_agent,
        ip_address=ctx.ip_address,
    )
    return tokens


@router.post("/refresh", response_model=TokenResponse, summary="Refresh an access token")
def refresh(payload: RefreshRequest, session: DbSession, ctx: RequestCtx) -> TokenResponse:
    """Rotate a refresh token.

    The presented token is revoked and a new pair is issued, so a stolen refresh
    token is usable at most once.
    """
    return AuthService(session).refresh(payload.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Log out",
)
def logout(
    session: DbSession,
    ctx: RequestCtx,
    user: CurrentUser,
    all_sessions: bool = False,
) -> Response:
    """Revoke refresh tokens. Pass ``all_sessions=true`` to sign out everywhere."""
    AuthService(session).logout(user.id, all_sessions=all_sessions)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=ProfileOut, summary="Current profile")
def me(session: DbSession, user: CurrentUser) -> ProfileOut:
    """Return the signed-in user with their profile and effective permissions."""
    return _profile(user, list(ROLE_PERMISSIONS.get(user.role, [])))


@router.patch("/me", response_model=ProfileOut, summary="Update own profile")
def update_me(payload: UserUpdateSelf, session: DbSession, user: CurrentUser) -> ProfileOut:
    """Update contact details and the role-specific sub-profile in one call."""
    updated = AuthService(session).update_self(user.id, payload)
    return _profile(updated, list(ROLE_PERMISSIONS.get(updated.role, [])))


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Change own password",
)
def change_password(
    payload: PasswordChangeRequest, session: DbSession, user: CurrentUser
) -> Response:
    """Require the current password; every existing session is revoked."""
    AuthService(session).change_password(user.id, payload.current_password, payload.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/roles", response_model=list[RoleOut], summary="List platform roles")
def list_roles(session: DbSession) -> list[RoleOut]:
    """Roles and their permission sets - used by the frontend to render selectors."""
    roles = RoleRepository(Role, session).find_all(order_by=["name"])
    return [
        RoleOut(
            id=role.id,
            name=role.name,
            display_name=role.display_name,
            description=role.description,
            permissions=list(role.permissions or []),
        )
        for role in roles
    ]


__all__ = ["router"]
