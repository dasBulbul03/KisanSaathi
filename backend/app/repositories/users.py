"""User and role repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.core.enums import UserRole, UserStatus, VerificationStatus
from app.models import (
    BuyerProfile,
    Notification,
    RefreshToken,
    Role,
    User,
)
from app.repositories.base import BaseRepository


class RoleRepository(BaseRepository[Role]):
    def get_by_name(self, name: UserRole) -> Role | None:
        return self.find_one_by(name=name)


class UserRepository(BaseRepository[User]):
    def _with_relations(self) -> Select:
        return self._base_query().options(
            joinedload(User.primary_role),
            selectinload(User.farmer_profile),
            selectinload(User.fpo_profile),
            selectinload(User.buyer_profile),
        )

    def get_with_profiles(self, user_id: uuid.UUID) -> User | None:
        return (
            self.session.execute(self._with_relations().where(User.id == user_id))
            .unique()
            .scalar_one_or_none()
        )

    def get_by_phone(self, phone: str) -> User | None:
        return self._find_with_profiles(phone=phone)

    def get_by_email(self, email: str) -> User | None:
        return self._find_with_profiles(email=email.lower())

    def get_by_identifier(self, identifier: str) -> User | None:
        if "@" in identifier:
            return self._find_with_profiles(email=identifier.lower())
        return self._find_with_profiles(phone=identifier)

    def _find_with_profiles(self, **filters: Any) -> User | None:
        stmt = self._with_relations()
        for key, value in filters.items():
            stmt = stmt.where(getattr(User, key) == value)
        return self.session.execute(stmt).unique().scalar_one_or_none()

    def phone_exists(self, phone: str) -> bool:
        return self.exists(phone=phone)

    def email_exists(self, email: str) -> bool:
        return self.exists(email=email.lower())

    def search(
        self,
        *,
        term: str | None = None,
        roles: Sequence[UserRole] | None = None,
        status: UserStatus | None = None,
        district: str | None = None,
        verification_status: VerificationStatus | None = None,
    ) -> Select:
        stmt = (
            self._base_query()
            .join(User.primary_role)
            .outerjoin(BuyerProfile, BuyerProfile.user_id == User.id)
            .options(joinedload(User.primary_role), selectinload(User.buyer_profile))
        )
        if term:
            pattern = f"%{term.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(User.full_name).like(pattern),
                    func.lower(User.phone).like(f"%{term.strip()}%"),
                    func.lower(func.coalesce(User.email, "")).like(pattern),
                    func.lower(func.coalesce(BuyerProfile.organisation_name, "")).like(pattern),
                )
            )
        if roles:
            stmt = stmt.where(Role.name.in_(list(roles)))
        if status is not None:
            stmt = stmt.where(User.status == status)
        if district:
            stmt = stmt.where(User.district == district)
        if verification_status is not None:
            stmt = stmt.where(BuyerProfile.verification_status == verification_status)
        return stmt

    def sellers_query(self, *, status: UserStatus | None = None) -> Select:
        """Farmers and FPOs only - backs the admin seller directory.

        Scoped by role so buyers and staff accounts never appear in a list of
        people who sell produce.
        """
        return (
            self._with_relations()
            .join(Role, User.primary_role_id == Role.id)
            .where(
                User.is_deleted.is_(False),
                Role.name.in_([UserRole.FARMER, UserRole.FPO]),
                *([User.status == status] if status is not None else []),
            )
            .order_by(User.created_at.desc())
        )

    def count_by_role(self) -> dict[str, int]:
        stmt = (
            select(Role.name, func.count(User.id))
            .select_from(User)
            .join(Role, User.primary_role_id == Role.id)
            .where(User.is_deleted.is_(False))
            .group_by(Role.name)
        )
        return {str(role): int(count) for role, count in self.session.execute(stmt).all()}

    def count_active(self) -> int:
        return self.count(is_deleted=False, status=UserStatus.ACTIVE)

    def count_new_since(self, days: int) -> int:
        from datetime import UTC, datetime, timedelta

        since = datetime.now(UTC) - timedelta(days=days)
        stmt = select(func.count(User.id)).where(
            User.created_at >= since, User.is_deleted.is_(False)
        )
        return int(self.session.execute(stmt).scalar_one())

    def district_breakdown(self) -> list[tuple[str, int]]:
        stmt = (
            select(User.district, func.count(User.id))
            .where(User.is_deleted.is_(False), User.district.isnot(None))
            .group_by(User.district)
            .order_by(func.count(User.id).desc())
        )
        return [(district, int(count)) for district, count in self.session.execute(stmt).all()]


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    def get_valid(self, token_hash: str) -> RefreshToken | None:
        return self.find_one_by(token_hash=token_hash, revoked_at=None)

    def revoke_for_user(self, user_id: uuid.UUID) -> int:
        from datetime import UTC, datetime

        tokens = self.find_all(filters={"user_id": user_id})
        now = datetime.now(UTC)
        for token in tokens:
            token.revoked_at = now
        self.session.flush()
        return len(tokens)

    def purge_expired(self) -> int:
        return self.bulk_delete()


class NotificationRepository(BaseRepository[Notification]):
    def for_user(self, user_id: uuid.UUID, *, unread_only: bool = False) -> list[Notification]:
        filters: dict[str, Any] = {"user_id": user_id}
        if unread_only:
            filters["is_read"] = False
        return self.find_all(filters=filters, order_by=["-created_at"], limit=100)

    def unread_count(self, user_id: uuid.UUID) -> int:
        return self.count(user_id=user_id, is_read=False)

    def mark_read(self, notification: Notification) -> Notification:
        from datetime import UTC, datetime

        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        self.session.flush()
        return notification

    def mark_all_read(self, user_id: uuid.UUID) -> int:
        from datetime import UTC, datetime

        items = self.find_all(filters={"user_id": user_id, "is_read": False})
        now = datetime.now(UTC)
        for item in items:
            item.is_read = True
            item.read_at = now
        self.session.flush()
        return len(items)
