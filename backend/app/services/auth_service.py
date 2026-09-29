"""Authentication and account services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.enums import BuyerType, NotificationType, UserRole, UserStatus
from app.core.exceptions import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.rbac import SELLER_ROLES
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from app.models import (
    BuyerProfile,
    FarmerProfile,
    FPOProfile,
    RefreshToken,
    Role,
    User,
)
from app.repositories.users import RefreshTokenRepository, RoleRepository, UserRepository
from app.schemas.user import (
    LoginRequest,
    RegisterRequest,
    StaffUserCreate,
    TokenResponse,
    UserUpdateSelf,
)
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.codes import farmer_id_code
from app.utils.geo import district_coords

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(User, session)
        self.roles = RoleRepository(Role, session)
        self.refresh_tokens = RefreshTokenRepository(RefreshToken, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    # ------------------------------------------------------------- helpers
    def _role(self, name: UserRole) -> Role:
        role = self.roles.get_by_name(name)
        if role is None:
            raise ConflictError(
                f"Role {name} is not configured. Run the database seed first.",
                code="ROLE_NOT_SEEDED",
            )
        return role

    def _issue_tokens(
        self, user: User, *, user_agent: str | None = None, ip_address: str | None = None
    ) -> TokenResponse:
        roles = [user.primary_role.name.value]
        roles.extend(link.role.name.value for link in user.role_links if link.is_active)
        access_token, expires_at = create_access_token(
            str(user.id), roles=list(dict.fromkeys(roles))
        )
        raw_refresh, refresh_expires, _ = create_refresh_token(str(user.id))
        self.refresh_tokens.create(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=refresh_expires,
            user_agent=(user_agent or "")[:400] or None,
            ip_address=ip_address,
        )
        from app.core.config import settings

        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            expires_at=expires_at,
        )

    # ------------------------------------------------------------ register
    def register(self, payload: RegisterRequest) -> tuple[User, TokenResponse]:
        phone = payload.phone
        if self.users.phone_exists(phone):
            raise ConflictError(
                "An account with this mobile number already exists.",
                code="PHONE_ALREADY_REGISTERED",
            )
        if payload.email and self.users.email_exists(payload.email):
            raise ConflictError(
                "An account with this email already exists.",
                code="EMAIL_ALREADY_REGISTERED",
            )
        try:
            validate_password_strength(payload.password)
        except ValueError as exc:
            raise PermissionDeniedError(str(exc), code="WEAK_PASSWORD") from exc

        role = self._role(payload.role)
        lat, lon = district_coords(payload.district)
        user = User(
            full_name=payload.full_name.strip(),
            phone=phone,
            email=payload.email.lower() if payload.email else None,
            password_hash=hash_password(payload.password),
            primary_role_id=role.id,
            status=UserStatus.ACTIVE,
            district=payload.district,
            is_phone_verified=False,
            is_email_verified=bool(payload.email),
        )
        self.session.add(user)
        self.session.flush()

        if payload.role is UserRole.FARMER:
            user.farmer_profile = FarmerProfile(
                farmer_id_code=farmer_id_code(),
                village=payload.village,
                taluka=payload.taluka,
                district=payload.district,
                latitude=lat,
                longitude=lon,
                farm_area_acres=payload.farm_area_acres,
                primary_crops=payload.primary_crops,
            )
        elif payload.role is UserRole.FPO:
            user.fpo_profile = FPOProfile(
                organisation_name=payload.organisation_name,
                village=payload.village,
                taluka=payload.taluka,
                district=payload.district,
                latitude=lat,
                longitude=lon,
                member_count=payload.member_count or 1,
                commodities=payload.primary_crops,
            )
        elif payload.role is UserRole.BUYER:
            user.buyer_profile = BuyerProfile(
                organisation_name=payload.organisation_name or payload.full_name,
                buyer_type=payload.buyer_type or BuyerType.WHOLESALER,
                gst_number=payload.gst_number,
                district=payload.district,
                taluka=payload.taluka,
                city=payload.taluka,
                commodities=payload.primary_crops,
            )
        self.session.flush()

        self.audit.record(
            action="USER_REGISTERED",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
            actor_role=payload.role,
            after={"phone": phone, "role": payload.role.value},
        )
        if payload.role is UserRole.BUYER:
            self.notifications.notify(
                user.id,
                notification_type=NotificationType.BUYER_VERIFICATION,
                title="Buyer verification pending",
                body=(
                    "Your buyer account has been created and is awaiting verification. "
                    "Verified buyers get a badge and priority in matching."
                ),
                link="/profile",
            )
        user.last_login_at = datetime.now(UTC)
        logger.info("auth.register", user_id=str(user.id), role=payload.role.value)
        return user, self._issue_tokens(user)

    # --------------------------------------------------------------- login
    def login(
        self,
        payload: LoginRequest,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, TokenResponse]:
        user = self.users.get_by_identifier(payload.identifier)
        if user is None or not verify_password(payload.password, user.password_hash):
            self.audit.record(
                action="LOGIN_FAILED",
                entity_type="user",
                entity_id=user.id if user else None,
                note=f"identifier={payload.identifier[:64]}",
            )
            raise AuthenticationError(
                "Incorrect mobile number / email or password.", code="INVALID_CREDENTIALS"
            )
        if user.status is not UserStatus.ACTIVE:
            raise PermissionDeniedError(
                f"This account is {user.status.value.lower()}. Contact support.",
                code="ACCOUNT_NOT_ACTIVE",
            )
        user.last_login_at = datetime.now(UTC)
        self.session.flush()
        self.audit.record(
            action="LOGIN",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
            actor_role=user.role,
        )
        logger.info("auth.login", user_id=str(user.id), role=user.role.value)
        return user, self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)

    # ------------------------------------------------------------- refresh
    def refresh(self, raw_token: str) -> TokenResponse:
        try:
            decode_token(raw_token, expected_type="refresh")
        except TokenError as exc:
            raise AuthenticationError("Refresh token is invalid or expired.") from exc
        record = self.refresh_tokens.get_valid(hash_token(raw_token))
        if record is None or record.expires_at < datetime.now(UTC):
            raise AuthenticationError("Refresh token is invalid or expired.")
        user = self.users.get_with_profiles(record.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise AuthenticationError("This account is not active.")
        record.revoked_at = datetime.now(UTC)
        self.session.flush()
        return self._issue_tokens(user)

    # -------------------------------------------------------------- logout
    def logout(
        self,
        user_id: uuid.UUID,
        *,
        current_refresh_token: str | None = None,
        all_sessions: bool = False,
    ) -> int:
        """Revoke refresh tokens. Without ``all_sessions`` only the caller's own
        session is ended, so signing out on one device keeps other devices signed in."""
        if all_sessions or not current_refresh_token:
            count = self.refresh_tokens.revoke_for_user(user_id)
        else:
            record = self.refresh_tokens.get_valid(hash_token(current_refresh_token))
            if record is None or record.user_id != user_id:
                raise AuthenticationError("Refresh token is invalid or expired.")
            record.revoked_at = datetime.now(UTC)
            self.session.flush()
            count = 1
        self.audit.record(
            action="LOGOUT",
            entity_type="user",
            entity_id=user_id,
            actor_user_id=user_id,
            after={"revoked_sessions": count, "all_sessions": all_sessions},
        )
        return count

    # ------------------------------------------------------- password mgmt
    def change_password(self, user_id: uuid.UUID, current: str, new: str) -> None:
        user = self.users.get(user_id)
        if user is None:
            raise AuthenticationError("User not found.")
        if not verify_password(current, user.password_hash):
            raise PermissionDeniedError("Current password is incorrect.")
        try:
            validate_password_strength(new)
        except ValueError as exc:
            raise PermissionDeniedError(str(exc), code="WEAK_PASSWORD") from exc
        user.password_hash = hash_password(new)
        self.session.flush()
        self.audit.record(
            action="PASSWORD_CHANGED",
            entity_type="user",
            entity_id=user_id,
            actor_user_id=user_id,
        )

    # -------------------------------------------------------- self updates
    def update_self(self, user_id: uuid.UUID, payload: UserUpdateSelf) -> User:
        user = self.users.get_with_profiles(user_id)
        if user is None:
            raise AuthenticationError("User not found.")
        before = {"full_name": user.full_name, "email": user.email, "district": user.district}
        if payload.full_name:
            user.full_name = payload.full_name.strip()
        if payload.email:
            if self.users.email_exists(payload.email):
                raise ConflictError("This email is already in use.", code="EMAIL_IN_USE")
            user.email = payload.email.lower()
            user.is_email_verified = False
        if payload.avatar_url is not None:
            user.avatar_url = payload.avatar_url
        if payload.preferred_language:
            user.preferred_language = payload.preferred_language
        if payload.district is not None:
            user.district = payload.district
            lat, lon = district_coords(payload.district)
            if user.farmer_profile:
                user.farmer_profile.district = payload.district
                user.farmer_profile.latitude = user.farmer_profile.latitude or lat
                user.farmer_profile.longitude = user.farmer_profile.longitude or lon
            if user.fpo_profile:
                user.fpo_profile.district = payload.district
                user.fpo_profile.latitude = user.fpo_profile.latitude or lat
                user.fpo_profile.longitude = user.fpo_profile.longitude or lon
            if user.buyer_profile:
                user.buyer_profile.district = payload.district
        self._apply_profile_updates(user, payload)
        self.session.flush()
        self.audit.record(
            action="PROFILE_UPDATED",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before=before,
            after={"full_name": user.full_name, "email": user.email, "district": user.district},
        )
        return user

    def _apply_profile_updates(self, user: User, payload: UserUpdateSelf) -> None:
        if payload.farmer and user.farmer_profile:
            for key, value in payload.farmer.model_dump(exclude_unset=True).items():
                setattr(user.farmer_profile, key, value)
        if payload.fpo and user.fpo_profile:
            for key, value in payload.fpo.model_dump(exclude_unset=True).items():
                setattr(user.fpo_profile, key, value)
        if payload.buyer and user.buyer_profile:
            for key, value in payload.buyer.model_dump(exclude_unset=True).items():
                setattr(user.buyer_profile, key, value)

    # -------------------------------------------------------------- lookup
    def authenticate_token(self, token: str) -> User:
        try:
            payload = decode_token(token, expected_type="access")
        except TokenError as exc:
            raise AuthenticationError(str(exc), code="INVALID_TOKEN") from exc
        try:
            user_id = uuid.UUID(payload["sub"])
        except (KeyError, ValueError) as exc:
            raise AuthenticationError("Malformed token subject.") from exc
        user = self.users.get_with_profiles(user_id)
        if user is None:
            raise AuthenticationError("Account no longer exists.")
        if user.status is not UserStatus.ACTIVE:
            raise PermissionDeniedError(
                f"This account is {user.status.value.lower()}.", code="ACCOUNT_NOT_ACTIVE"
            )
        return user

    def load_user(self, user_id: uuid.UUID) -> User | None:
        return self.users.get_with_profiles(user_id)


class AdminUserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(User, session)
        self.roles = RoleRepository(Role, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    def set_status(
        self,
        user_id: uuid.UUID,
        status: UserStatus,
        *,
        actor_id: uuid.UUID,
        reason: str | None = None,
    ) -> User:
        user = self.users.get_with_profiles(user_id)
        if user is None:
            raise AuthenticationError("User not found.", code="USER_NOT_FOUND", status_code=404)
        if user.primary_role.name is UserRole.ADMIN and status is not UserStatus.ACTIVE:
            if self.users.count_by_role().get(UserRole.ADMIN.value, 0) <= 1:
                raise ConflictError(
                    "At least one active administrator is required.",
                    code="LAST_ADMIN",
                )
        before = {"status": user.status.value}
        user.status = status
        self.session.flush()
        self.audit.record(
            action="USER_STATUS_CHANGED",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=actor_id,
            actor_role=UserRole.ADMIN,
            before=before,
            after={"status": status.value},
            note=reason,
        )
        self.notifications.notify(
            user.id,
            notification_type=NotificationType.SYSTEM,
            title=f"Account status changed to {status.value.lower()}",
            body=reason or "Your account status was updated by an administrator.",
            link="/profile",
        )
        return user

    def verify_buyer(
        self,
        buyer_user_id: uuid.UUID,
        *,
        approved: bool,
        actor_id: uuid.UUID,
        notes: str | None = None,
    ) -> BuyerProfile:
        from app.core.enums import VerificationStatus

        user = self.users.get_with_profiles(buyer_user_id)
        if user is None or user.buyer_profile is None:
            raise AuthenticationError("Buyer not found.", code="BUYER_NOT_FOUND", status_code=404)
        profile = user.buyer_profile
        before = {"verification_status": profile.verification_status.value}
        profile.verification_status = (
            VerificationStatus.VERIFIED if approved else VerificationStatus.REJECTED
        )
        profile.verified_at = datetime.now(UTC) if approved else None
        profile.verified_by_user_id = actor_id
        profile.verification_notes = notes
        self.session.flush()
        self.audit.record(
            action="BUYER_VERIFIED" if approved else "BUYER_REJECTED",
            entity_type="buyer_profile",
            entity_id=profile.id,
            actor_user_id=actor_id,
            actor_role=UserRole.ADMIN,
            before=before,
            after={"verification_status": profile.verification_status.value},
            note=notes,
        )
        self.notifications.notify(
            user.id,
            notification_type=NotificationType.BUYER_VERIFICATION,
            title=(
                "Your buyer account is verified"
                if approved
                else "Buyer verification was not approved"
            ),
            body=(
                "You now carry the Verified Buyer badge and appear with priority in matching."
                if approved
                else (notes or "Please review your GSTIN and registration documents.")
            ),
            link="/profile",
        )
        return profile

    def sellers(self) -> list[User]:
        """Farmers and FPOs, newest first.

        Deliberately role-scoped: this backs the admin seller directory, and
        returning buyers and staff there would be misleading.
        """
        stmt = self.users.sellers_query().limit(500)
        return list(self.session.execute(stmt).unique().scalars().all())

    def create_staff_user(
        self, payload: StaffUserCreate, *, actor_id: uuid.UUID | None = None
    ) -> User:
        """Onboard an administrator, quality inspector or logistics partner.

        ``actor_id`` may be ``None`` only for the first bootstrap administrator.
        """
        if self.users.phone_exists(payload.phone):
            raise ConflictError(
                "An account with this mobile number already exists.",
                code="PHONE_ALREADY_REGISTERED",
            )
        if payload.email and self.users.email_exists(payload.email):
            raise ConflictError(
                "An account with this email already exists.",
                code="EMAIL_ALREADY_REGISTERED",
            )
        try:
            validate_password_strength(payload.password)
        except ValueError as exc:
            raise PermissionDeniedError(str(exc), code="WEAK_PASSWORD") from exc

        role = self.roles.get_by_name(payload.role)
        if role is None:
            raise ConflictError(
                f"Role {payload.role} is not configured. Run the database seed first.",
                code="ROLE_NOT_SEEDED",
            )
        lat, lon = district_coords(payload.district)
        user = User(
            full_name=payload.full_name.strip(),
            phone=payload.phone,
            email=payload.email.lower() if payload.email else None,
            password_hash=hash_password(payload.password),
            primary_role_id=role.id,
            status=UserStatus.ACTIVE if payload.is_active else UserStatus.PENDING,
            is_phone_verified=True,
            is_email_verified=bool(payload.email),
            district=payload.district,
            created_by_user_id=actor_id,
        )
        self.session.add(user)
        self.session.flush()
        self.audit.record(
            action="STAFF_USER_CREATED",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=actor_id,
            actor_role=UserRole.ADMIN,
            after={
                "phone": user.phone,
                "role": payload.role.value,
                "organisation_name": payload.organisation_name,
            },
        )
        self.notifications.notify(
            user.id,
            notification_type=NotificationType.SYSTEM,
            title="Welcome to KisanSaathi",
            body=(
                f"An administrator created your {payload.role.value.replace('_', ' ').lower()} "
                "account. Sign in with the mobile number and temporary password you were given."
            ),
            link="/login",
        )
        logger.info("auth.staff_created", user_id=str(user.id), role=payload.role.value)
        return user


def ensure_seller(user: User) -> bool:
    return user.role in SELLER_ROLES


def token_ttl_seconds() -> int:
    from app.core.config import settings

    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def purge_stale_refresh_tokens(session: Session) -> int:
    repo = RefreshTokenRepository(RefreshToken, session)
    cutoff = datetime.now(UTC) - timedelta(days=30)
    removed = 0
    for token in repo.find_all(order_by=["-created_at"]):
        if token.expires_at < cutoff:
            session.delete(token)
            removed += 1
    session.flush()
    return removed


__all__ = [
    "AdminUserService",
    "AuthService",
    "ensure_seller",
    "purge_stale_refresh_tokens",
    "token_ttl_seconds",
]
