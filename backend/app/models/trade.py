"""Trade lifecycle models: lots, demands, offers, orders, transactions."""

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
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    DemandStatus,
    LotStatus,
    OfferStatus,
    OrderStatus,
    PaymentTerms,
    QualityGrade,
    SellerType,
)
from app.db.base import JSON, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.catalog import Commodity
    from app.models.logistics import LogisticsRequest
    from app.models.quality import QualityInspection
    from app.models.user import BuyerProfile, User


class FarmLot(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "farm_lots"

    seller_type: Mapped[SellerType] = mapped_column(
        SAEnum(SellerType, name="seller_type", native_enum=False, length=16),
        nullable=False,
        index=True,
    )
    seller_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commodity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commodities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    lot_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    available_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="quintal", nullable=False)
    expected_price: Mapped[float | None] = mapped_column(Float)
    minimum_price: Mapped[float | None] = mapped_column(Float)
    quality_grade: Mapped[QualityGrade] = mapped_column(
        SAEnum(QualityGrade, name="quality_grade", native_enum=False, length=16),
        default=QualityGrade.GRADE_A,
        nullable=False,
        index=True,
    )
    quality_specs: Mapped[dict] = mapped_column(JSON, default=dict)
    harvest_date: Mapped[date | None] = mapped_column(Date)
    available_from: Mapped[date | None] = mapped_column(Date, index=True)
    village: Mapped[str | None] = mapped_column(String(120))
    taluka: Mapped[str | None] = mapped_column(String(120), index=True)
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(80), default="Maharashtra")
    pincode: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    pickup_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    seller_handles_transport: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    storage_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    organic_certified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[LotStatus] = mapped_column(
        SAEnum(LotStatus, name="lot_status", native_enum=False, length=24),
        default=LotStatus.DRAFT,
        nullable=False,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_offers_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    seller: Mapped[User] = relationship(foreign_keys=[seller_user_id])
    commodity: Mapped[Commodity] = relationship(back_populates="lots")  # type: ignore[name-defined]
    images: Mapped[list[LotImage]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )
    offers: Mapped[list[Offer]] = relationship(
        back_populates="lot",
        cascade="all, delete-orphan",
        foreign_keys="Offer.lot_id",
    )
    inspections: Mapped[list[QualityInspection]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_farm_lots_browse", "status", "commodity_id", "district"),
        Index("ix_farm_lots_seller_status", "seller_user_id", "status"),
    )


class LotImage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "lot_images"

    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farm_lots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(200))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    lot: Mapped[FarmLot] = relationship(back_populates="images")


class BuyerDemand(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "buyer_demands"

    buyer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commodity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commodities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    required_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="quintal", nullable=False)
    min_grade: Mapped[QualityGrade] = mapped_column(
        SAEnum(QualityGrade, name="demand_quality_grade", native_enum=False, length=16),
        default=QualityGrade.GRADE_B,
        nullable=False,
        index=True,
    )
    quality_specs: Mapped[dict] = mapped_column(JSON, default=dict)
    min_price_per_unit: Mapped[float | None] = mapped_column(Float)
    max_price_per_unit: Mapped[float | None] = mapped_column(Float)
    delivery_location: Mapped[str] = mapped_column(String(240), nullable=False)
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    taluka: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    max_pickup_radius_km: Mapped[float] = mapped_column(Float, default=250.0, nullable=False)
    required_by_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    delivery_window_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    payment_terms: Mapped[PaymentTerms] = mapped_column(
        SAEnum(PaymentTerms, name="demand_payment_terms", native_enum=False, length=24),
        default=PaymentTerms.NET_7,
        nullable=False,
    )
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    requires_verified_buyer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[DemandStatus] = mapped_column(
        SAEnum(DemandStatus, name="demand_status", native_enum=False, length=24),
        default=DemandStatus.OPEN,
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    fulfilled_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    #: Joins through ``users.id``: a demand always belongs to a registered buyer.
    buyer: Mapped[BuyerProfile] = relationship(
        back_populates="demands",
        primaryjoin="foreign(BuyerDemand.buyer_user_id) == BuyerProfile.user_id",
        overlaps="demands",
    )
    buyer_user: Mapped[User] = relationship(foreign_keys=[buyer_user_id], overlaps="buyer,demands")
    commodity: Mapped[Commodity] = relationship()
    offers: Mapped[list[Offer]] = relationship(
        back_populates="demand", foreign_keys="Offer.demand_id"
    )

    __table_args__ = (
        Index("ix_buyer_demands_match", "status", "commodity_id", "required_by_date"),
    )


class Offer(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "offers"

    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farm_lots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    buyer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    demand_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("buyer_demands.id", ondelete="SET NULL"), index=True
    )
    reference_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    offered_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="quintal", nullable=False)
    delivery_terms: Mapped[str | None] = mapped_column(String(200))
    payment_terms: Mapped[PaymentTerms] = mapped_column(
        SAEnum(PaymentTerms, name="offer_payment_terms", native_enum=False, length=24),
        default=PaymentTerms.NET_7,
        nullable=False,
    )
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[OfferStatus] = mapped_column(
        SAEnum(OfferStatus, name="offer_status", native_enum=False, length=16),
        default=OfferStatus.PENDING,
        nullable=False,
        index=True,
    )
    parent_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offers.id", ondelete="SET NULL"), index=True
    )
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    responded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decline_reason: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    lot: Mapped[FarmLot] = relationship(back_populates="offers", foreign_keys=[lot_id])
    buyer: Mapped[User] = relationship(foreign_keys=[buyer_user_id])
    demand: Mapped[BuyerDemand | None] = relationship(back_populates="offers")
    parent_offer: Mapped[Offer | None] = relationship(
        remote_side="Offer.id", foreign_keys=[parent_offer_id]
    )
    counters: Mapped[list[Offer]] = relationship(
        back_populates="parent_offer", cascade="all, delete-orphan"
    )
    order: Mapped[Order | None] = relationship(
        back_populates="offer", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_offers_lot_status", "lot_id", "status"),
        Index("ix_offers_buyer_status", "buyer_user_id", "status"),
    )


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "orders"

    order_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offers.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("farm_lots.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    buyer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    seller_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    commodity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commodities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="quintal", nullable=False)
    agreed_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    quality_grade: Mapped[QualityGrade] = mapped_column(
        SAEnum(QualityGrade, name="order_quality_grade", native_enum=False, length=16),
        nullable=False,
    )
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status", native_enum=False, length=32),
        default=OrderStatus.ORDER_CREATED,
        nullable=False,
        index=True,
    )
    pickup_location: Mapped[str] = mapped_column(String(240), nullable=False)
    pickup_district: Mapped[str | None] = mapped_column(String(80), index=True)
    delivery_location: Mapped[str] = mapped_column(String(240), nullable=False)
    delivery_district: Mapped[str | None] = mapped_column(String(80), index=True)
    pickup_date: Mapped[date | None] = mapped_column(Date)
    delivery_date: Mapped[date | None] = mapped_column(Date)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status_history: Mapped[list] = mapped_column(JSON, default=list)
    cancelled_reason: Mapped[str | None] = mapped_column(String(255))

    offer: Mapped[Offer] = relationship(back_populates="order")
    lot: Mapped[FarmLot] = relationship(foreign_keys=[lot_id])
    buyer: Mapped[User] = relationship(foreign_keys=[buyer_user_id])
    seller: Mapped[User] = relationship(foreign_keys=[seller_user_id])
    commodity: Mapped[Commodity] = relationship()
    logistics_request: Mapped[LogisticsRequest | None] = relationship(  # type: ignore[name-defined]
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
    transaction: Mapped[Transaction | None] = relationship(  # type: ignore[name-defined]
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
    inspections: Mapped[list[QualityInspection]] = relationship(  # type: ignore[name-defined]
        back_populates="order"
    )

    __table_args__ = (
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_buyer_status", "buyer_user_id", "status"),
        Index("ix_orders_seller_status", "seller_user_id", "status"),
    )


class Transaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Ledger record mirroring a commercial order. Money movement is tracked,
    never executed - see ``docs/ai.md`` for the AI safety boundary."""

    __tablename__ = "transactions"

    transaction_reference: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    seller_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    buyer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    commodity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commodities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="quintal", nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    platform_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="transaction_status", native_enum=False, length=32),
        default=OrderStatus.ORDER_CREATED,
        nullable=False,
        index=True,
    )
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    initiated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    order: Mapped[Order] = relationship(back_populates="transaction")
    payments: Mapped[list[Payment]] = relationship(  # type: ignore[name-defined] # noqa: F821
        back_populates="transaction", cascade="all, delete-orphan"
    )
