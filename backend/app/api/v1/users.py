"""Administrative user management endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.deps import DbSession, Pagination, require_permissions, require_roles
from app.core.enums import UserRole, UserStatus, VerificationStatus
from app.core.exceptions import NotFoundError
from app.core.rbac import BUYER_VERIFY, ROLE_PERMISSIONS, USER_MANAGE, USER_READ_ALL
from app.models import User
from app.repositories.users import UserRepository
from app.schemas.common import Page
from app.schemas.user import (
    BuyerProfileOut,
    FarmerProfileOut,
    FPOProfileOut,
    ProfileOut,
    StaffUserCreate,
    UserListItem,
    UserStatusUpdate,
    UserSummary,
)
from app.services.auth_service import AdminUserService

# ``CurrentAdmin`` is an ``Annotated`` alias and FastAPI cannot resolve one inside
# ``Depends(...)`` at router level - it would register phantom query parameters -
# so the blanket guard names the underlying role dependency.
router = APIRouter(
    prefix="/admin/users",
    tags=["admin"],
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)

UserReader = Annotated[User, Depends(require_permissions(USER_READ_ALL))]
UserAdministrator = Annotated[User, Depends(require_permissions(USER_MANAGE))]
BuyerVerifier = Annotated[User, Depends(require_permissions(BUYER_VERIFY))]


class VerifyBuyerRequest(BaseModel):
    """An administrator's decision on a buyer's verification request."""

    approved: bool = Field(description="Verify the buyer, or reject the request")
    notes: str | None = Field(
        default=None, max_length=1000, description="Reason shared with the buyer"
    )


def _list_item(user: User) -> UserListItem:
    """Project a user row for the admin roster.

    ``organisation_name`` and ``verification_status`` live on the FPO / buyer
    sub-profiles rather than on ``users``, so they are resolved here instead of
    by attribute-based validation.
    """
    farmer, fpo, buyer = user.farmer_profile, user.fpo_profile, user.buyer_profile
    place = farmer or fpo or buyer
    organisation = fpo or buyer
    return UserListItem(
        id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        role=user.role,
        status=user.status,
        district=user.district,
        taluka=place.taluka if place else None,
        village=farmer.village if farmer else (fpo.village if fpo else None),
        organisation_name=organisation.organisation_name if organisation else None,
        verification_status=buyer.verification_status if buyer else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


def _detail(user: User) -> ProfileOut:
    """Assemble any account's profile plus the flat permission list it confers.

    Mirrors the self-service profile shape so a moderator reads one document.
    """
    return ProfileOut(
        user=UserSummary.model_validate(user),
        farmer=FarmerProfileOut.model_validate(user.farmer_profile)
        if user.farmer_profile
        else None,
        fpo=FPOProfileOut.model_validate(user.fpo_profile) if user.fpo_profile else None,
        buyer=BuyerProfileOut.model_validate(user.buyer_profile) if user.buyer_profile else None,
        permissions=list(ROLE_PERMISSIONS.get(user.role, [])),
    )


@router.get("", response_model=Page[UserListItem], summary="Search user accounts")
def list_users(
    session: DbSession,
    params: Pagination,
    user: UserReader,
    term: str | None = Query(None, description="Name, phone, email or organisation"),
    roles: list[UserRole] | None = Query(None, description="Restrict to these roles"),
    status_filter: UserStatus | None = Query(
        None, alias="status", description="Restrict to one account status"
    ),
    district: str | None = Query(None, description="Exact district match"),
    verification_status: VerificationStatus | None = Query(
        None, description="Buyer verification state"
    ),
) -> Page[UserListItem]:
    """Search every account on the platform.

    ``term`` matches name, phone, email or buyer organisation, so a moderator
    can find an account from whichever identifier the member quotes at them.
    """
    repo = UserRepository(User, session)
    rows, total = repo.paginate(
        stmt=repo.search(
            term=term,
            roles=roles,
            status=status_filter,
            district=district,
            verification_status=verification_status,
        ),
        page=params.page,
        page_size=params.page_size,
    )
    return Page[UserListItem].build([_list_item(row) for row in rows], total, params)


@router.get("/counts", response_model=dict[str, Any], summary="User totals")
def user_counts(
    session: DbSession,
    user: UserReader,
    days: int = Query(30, ge=1, le=365, description="Window for the new signups count"),
) -> dict[str, Any]:
    """Headline registration numbers for the admin dashboard.

    ``new_since`` counts signups inside the requested window only, so the
    dashboard can show a "joined this month" figure alongside the totals.
    """
    repo = UserRepository(User, session)
    return {
        "by_role": repo.count_by_role(),
        "active": repo.count_active(),
        "window_days": days,
        "new_since": repo.count_new_since(days),
    }


@router.get("/sellers", response_model=list[UserListItem], summary="Newest accounts")
def list_sellers(session: DbSession, user: UserReader) -> list[UserListItem]:
    """The most recently registered accounts, for the roster and picker lists."""
    return [_list_item(row) for row in AdminUserService(session).sellers()]


@router.post(
    "",
    response_model=UserListItem,
    status_code=status.HTTP_201_CREATED,
    summary="Create a staff account",
)
def create_staff_user(
    payload: StaffUserCreate, session: DbSession, user: UserAdministrator
) -> UserListItem:
    """Onboard an ADMIN, QUALITY_INSPECTOR or LOGISTICS_PARTNER account.

    These roles can never self-register, so this endpoint is the only way they
    come into existence; the account signs in with the phone number and
    temporary password set here.
    """
    created = AdminUserService(session).create_staff_user(payload, actor_id=user.id)
    session.commit()
    return _list_item(created)


@router.get("/{user_id}", response_model=ProfileOut, summary="Account detail")
def get_user(user_id: uuid.UUID, session: DbSession, user: UserReader) -> ProfileOut:
    """Full profile of any account, for support and moderation lookups."""
    record = UserRepository(User, session).get_with_profiles(user_id)
    if record is None:
        raise NotFoundError("User not found.", code="USER_NOT_FOUND")
    return _detail(record)


@router.patch(
    "/{user_id}/status",
    response_model=UserListItem,
    summary="Change account status",
)
def update_user_status(
    user_id: uuid.UUID,
    payload: UserStatusUpdate,
    session: DbSession,
    user: UserAdministrator,
) -> UserListItem:
    """Suspend, reactivate or reject an account.

    The reason is kept on the audit trail and shown to the member; the platform
    always keeps at least one active administrator.
    """
    updated = AdminUserService(session).set_status(
        user_id, payload.status, actor_id=user.id, reason=payload.reason
    )
    session.commit()
    return _list_item(updated)


@router.post(
    "/{user_id}/verify-buyer",
    response_model=BuyerProfileOut,
    summary="Approve or reject a buyer",
)
def verify_buyer(
    user_id: uuid.UUID,
    payload: VerifyBuyerRequest,
    session: DbSession,
    user: BuyerVerifier,
) -> BuyerProfileOut:
    """Decide a pending buyer verification.

    Approval grants the Verified Buyer badge and priority in matching; the notes
    are sent to the buyer either way.
    """
    profile = AdminUserService(session).verify_buyer(
        user_id, approved=payload.approved, actor_id=user.id, notes=payload.notes
    )
    session.commit()
    return BuyerProfileOut.model_validate(profile)


__all__ = ["router"]
