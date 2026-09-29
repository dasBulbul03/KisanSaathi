"""Reference data: commodities, markets, quality attribute definitions."""

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

from app.core.enums import MarketType, SyncStatus
from app.db.base import JSON, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.market import MarketPrice


class Commodity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "commodities"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name_hindi: Mapped[str | None] = mapped_column(String(120))
    name_marathi: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    default_unit: Mapped[str] = mapped_column(String(24), default="quintal", nullable=False)
    permitted_units: Mapped[list] = mapped_column(JSON, default=lambda: ["quintal", "tonne", "kg"])
    is_perishable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    seasonality_note: Mapped[str | None] = mapped_column(String(255))
    min_price_floor: Mapped[float | None] = mapped_column(Float)
    max_price_ceiling: Mapped[float | None] = mapped_column(Float)
    image_url: Mapped[str | None] = mapped_column(String(400))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)

    prices: Mapped[list[MarketPrice]] = relationship(
        back_populates="commodity", cascade="all, delete-orphan"
    )
    quality_attributes: Mapped[list[QualityAttribute]] = relationship(
        back_populates="commodity", cascade="all, delete-orphan"
    )
    lots: Mapped[list[FarmLot]] = relationship(  # type: ignore[name-defined] # noqa: F821
        back_populates="commodity"
    )
    demands: Mapped[list[BuyerDemand]] = relationship(  # type: ignore[name-defined] # noqa: F821
        back_populates="commodity"
    )


class Market(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "markets"

    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    market_type: Mapped[MarketType] = mapped_column(
        SAEnum(MarketType, name="market_type", native_enum=False, length=32),
        default=MarketType.APMC_MANDI,
        nullable=False,
        index=True,
    )
    district: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    taluka: Mapped[str | None] = mapped_column(String(120), index=True)
    state: Mapped[str] = mapped_column(String(80), default="Maharashtra", index=True)
    address: Mapped[str | None] = mapped_column(String(300))
    pincode: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    apmc_number: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    has_storage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_weighbridge: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trading_hours: Mapped[str | None] = mapped_column(String(120))

    prices: Mapped[list[MarketPrice]] = relationship(
        back_populates="market", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_markets_district_type", "district", "market_type"),)


class QualityAttribute(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Commodity specific quality parameter definition (e.g. tomato firmness)."""

    __tablename__ = "quality_attributes"

    commodity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commodities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(24))
    data_type: Mapped[str] = mapped_column(String(16), default="decimal", nullable=False)
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    ideal_min: Mapped[float | None] = mapped_column(Float)
    ideal_max: Mapped[float | None] = mapped_column(Float)
    grade_a_min: Mapped[float | None] = mapped_column(Float)
    grade_b_min: Mapped[float | None] = mapped_column(Float)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))

    commodity: Mapped[Commodity] = relationship(back_populates="quality_attributes")
    measurements: Mapped[list[QualityMeasurement]] = relationship(  # type: ignore[name-defined] # noqa: F821
        back_populates="attribute", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("commodity_id", "code", name="uq_quality_attributes"),)


class MarketDataSyncLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Audit trail for market data provider runs (admin "manage market data")."""

    __tablename__ = "market_data_sync_logs"

    provider: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[SyncStatus] = mapped_column(
        SAEnum(SyncStatus, name="sync_status", native_enum=False, length=16),
        default=SyncStatus.RUNNING,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    commodity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("commodities.id", ondelete="SET NULL")
    )
    market_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("markets.id", ondelete="SET NULL")
    )
    from_date: Mapped[date | None] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date)
    message: Mapped[str | None] = mapped_column(Text)
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
