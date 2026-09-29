"""User, role and role-specific profile models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    BuyerType,
    PaymentTerms,
    UserRole,
    UserStatus,
    VerificationStatus,
)
from app.db.base import (
    JSON,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.db.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.trade import BuyerDemand, FarmLot


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Permission catalogue. Seeded by ``app.db.seed``."""

    __tablename__ = "roles"

    name: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", native_enum=False, length=32),
        unique=True,
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    permissions: Mapped[list] = mapped_column(JSON, default=list)

    user_links: Mapped[list[UserRole]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status", native_enum=False, length=16),
        default=UserStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(400))
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(80), default="Maharashtra")
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    primary_role: Mapped[Role] = relationship(foreign_keys=[primary_role_id], lazy="joined")
    role_links: Mapped[list[UserRole]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserRole.user_id",
    )
    farmer_profile: Mapped[FarmerProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    fpo_profile: Mapped[FPOProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    buyer_profile: Mapped[BuyerProfile | None] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="BuyerProfile.user_id",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    notifications: Mapped[list[Notification]] = relationship(  # type: ignore[name-defined]
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_users_role_status", "primary_role_id", "status"),)

    @property
    def role(self) -> UserRole:
        return self.primary_role.name

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    @property
    def all_permissions(self) -> set[str]:
        perms: set[str] = set(self.primary_role.permissions or [])
        for link in self.role_links:
            if link.is_active:
                perms.update(link.role.permissions or [])
        return perms

    def has_permission(self, permission: str) -> bool:
        return permission in self.all_permissions


class UserRole(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Additional (non primary) roles assigned to a user."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    user: Mapped[User] = relationship(back_populates="role_links", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(back_populates="user_links")

    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles"),)


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class FarmerProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "farmer_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    farmer_id_code: Mapped[str | None] = mapped_column(String(64), index=True)
    village: Mapped[str | None] = mapped_column(String(120))
    taluka: Mapped[str | None] = mapped_column(String(120), index=True)
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(80), default="Maharashtra")
    pincode: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    farm_area_acres: Mapped[float | None] = mapped_column(Float)
    farming_since: Mapped[date | None] = mapped_column(Date)
    irrigation_source: Mapped[str | None] = mapped_column(String(120))
    primary_crops: Mapped[list] = mapped_column(JSON, default=list)
    annual_production_quintal: Mapped[float | None] = mapped_column(Float)
    preferred_market_ids: Mapped[list] = mapped_column(JSON, default=list)
    storage_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    storage_capacity_quintal: Mapped[float | None] = mapped_column(Float)
    bank_name: Mapped[str | None] = mapped_column(String(120))
    bank_account_last4: Mapped[str | None] = mapped_column(String(4))
    ifsc_code: Mapped[str | None] = mapped_column(String(16))
    upi_id: Mapped[str | None] = mapped_column(String(120))
    kcc_number: Mapped[str | None] = mapped_column(String(40))

    user: Mapped[User] = relationship(
        back_populates="farmer_profile", foreign_keys="FarmerProfile.user_id"
    )
    #: Read-only view of lots sold through this profile (joins via ``users.id``).
    lots: Mapped[list[FarmLot]] = relationship(
        viewonly=True,
        primaryjoin="FarmerProfile.user_id == foreign(FarmLot.seller_user_id)",
    )


class FPOProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "fpo_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    organisation_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    registration_number: Mapped[str | None] = mapped_column(String(80), index=True)
    registration_authority: Mapped[str | None] = mapped_column(String(160))
    registration_date: Mapped[date | None] = mapped_column(Date)
    pan_number: Mapped[str | None] = mapped_column(String(20))
    gst_number: Mapped[str | None] = mapped_column(String(20))
    fpo_type: Mapped[str | None] = mapped_column(String(80))
    village: Mapped[str | None] = mapped_column(String(120))
    taluka: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(80), default="Maharashtra")
    pincode: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    women_member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    commodities: Mapped[list] = mapped_column(JSON, default=list)
    aggregate_capacity_quintal: Mapped[float | None] = mapped_column(Float)
    annual_turnover_lakhs: Mapped[float | None] = mapped_column(Float)
    storage_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    storage_capacity_quintal: Mapped[float | None] = mapped_column(Float)
    cold_storage_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(160))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(String(200))

    user: Mapped[User] = relationship(
        back_populates="fpo_profile", foreign_keys="FPOProfile.user_id"
    )
    #: Read-only view of lots sold through this profile (joins via ``users.id``).
    lots: Mapped[list[FarmLot]] = relationship(
        viewonly=True,
        primaryjoin="FPOProfile.user_id == foreign(FarmLot.seller_user_id)",
    )


class BuyerProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "buyer_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    organisation_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    buyer_type: Mapped[BuyerType] = mapped_column(
        SAEnum(BuyerType, name="buyer_type", native_enum=False, length=32),
        default=BuyerType.WHOLESALER,
        nullable=False,
        index=True,
    )
    gst_number: Mapped[str | None] = mapped_column(String(20), index=True)
    pan_number: Mapped[str | None] = mapped_column(String(20))
    fssai_licence: Mapped[str | None] = mapped_column(String(60))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, name="verification_status", native_enum=False, length=16),
        default=VerificationStatus.PENDING,
        nullable=False,
        index=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    verification_notes: Mapped[str | None] = mapped_column(Text)
    document_url: Mapped[str | None] = mapped_column(String(400))
    commodities: Mapped[list] = mapped_column(JSON, default=list)
    monthly_volume_quintal: Mapped[float | None] = mapped_column(Float)
    quality_requirements: Mapped[list] = mapped_column(JSON, default=list)
    payment_terms: Mapped[PaymentTerms] = mapped_column(
        SAEnum(PaymentTerms, name="payment_terms", native_enum=False, length=24),
        default=PaymentTerms.NET_7,
        nullable=False,
    )
    default_payment_terms_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    purchasing_locations: Mapped[list] = mapped_column(JSON, default=list)
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    taluka: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(80), default="Maharashtra")
    pincode: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    contact_person: Mapped[str | None] = mapped_column(String(160))
    website: Mapped[str | None] = mapped_column(String(200))

    user: Mapped[User] = relationship(
        back_populates="buyer_profile", foreign_keys="BuyerProfile.user_id"
    )
    #: A demand belongs to the buyer *user*; this joins through ``users.id``.
    demands: Mapped[list[BuyerDemand]] = relationship(
        back_populates="buyer",
        primaryjoin="BuyerProfile.user_id == foreign(BuyerDemand.buyer_user_id)",
        overlaps="buyer,buyer_user",
    )


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    notification_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    link: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship(back_populates="notifications")

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    before_state: Mapped[dict | None] = mapped_column(JSON)
    after_state: Mapped[dict | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    note: Mapped[str | None] = mapped_column(Text)

    actor: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])

    @property
    def actor_name(self) -> str | None:
        """Display name of the actor, or ``"system"`` for unattributed entries.

        Exposed as a property so ``AuditLogOut.model_validate(log)`` can populate
        ``actor_name`` directly instead of needing a bespoke enrichment dict.
        """
        return self.actor.full_name if self.actor is not None else None
