"""Logistics and storage models."""

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

from app.core.enums import LogisticsStatus, StorageType, VehicleType
from app.db.base import JSON, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.trade import Order
    from app.models.user import User


class LogisticsRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "logistics_requests"

    reference_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    provider_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[LogisticsStatus] = mapped_column(
        SAEnum(LogisticsStatus, name="logistics_status", native_enum=False, length=24),
        default=LogisticsStatus.REQUESTED,
        nullable=False,
        index=True,
    )
    pickup_location: Mapped[str] = mapped_column(String(240), nullable=False)
    pickup_district: Mapped[str | None] = mapped_column(String(80), index=True)
    pickup_latitude: Mapped[float | None] = mapped_column(Float)
    pickup_longitude: Mapped[float | None] = mapped_column(Float)
    destination: Mapped[str] = mapped_column(String(240), nullable=False)
    destination_district: Mapped[str | None] = mapped_column(String(80), index=True)
    destination_latitude: Mapped[float | None] = mapped_column(Float)
    destination_longitude: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="quintal", nullable=False)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        SAEnum(VehicleType, name="vehicle_type", native_enum=False, length=24),
        default=VehicleType.TEMPO,
        nullable=False,
    )
    vehicle_number: Mapped[str | None] = mapped_column(String(24))
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    actual_cost: Mapped[float | None] = mapped_column(Float)
    transporter_name: Mapped[str | None] = mapped_column(String(160))
    transporter_contact: Mapped[str | None] = mapped_column(String(20))
    pickup_date: Mapped[date | None] = mapped_column(Date)
    delivery_date: Mapped[date | None] = mapped_column(Date)
    pickup_actual_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    delivery_actual_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    tracking_number: Mapped[str | None] = mapped_column(String(80), index=True)
    tracking_url: Mapped[str | None] = mapped_column(String(400))
    provider_reference: Mapped[str | None] = mapped_column(String(120))
    cold_chain_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status_history: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)

    order: Mapped[Order] = relationship(back_populates="logistics_request")
    provider: Mapped[User] = relationship(foreign_keys=[provider_user_id])

    __table_args__ = (Index("ix_logistics_provider_status", "provider_user_id", "status"),)


class LogisticsQuote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Rate card style quotes returned by a LogisticsProvider implementation."""

    __tablename__ = "logistics_quotes"

    provider_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    provider_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="demo", nullable=False)
    origin_district: Mapped[str | None] = mapped_column(String(80), index=True)
    destination_district: Mapped[str | None] = mapped_column(String(80), index=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        SAEnum(VehicleType, name="quote_vehicle_type", native_enum=False, length=24),
        nullable=False,
    )
    min_distance_km: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_distance_km: Mapped[float] = mapped_column(Float, default=10000.0, nullable=False)
    base_rate: Mapped[float] = mapped_column(Float, nullable=False)
    per_km_rate: Mapped[float] = mapped_column(Float, nullable=False)
    per_quintal_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    min_charge: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    transit_days: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    cold_chain_surcharge: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    rating: Mapped[float] = mapped_column(Float, default=4.0, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_logistics_quotes_route", "origin_district", "destination_district"),
    )


class StorageFacility(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "storage_facilities"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    storage_type: Mapped[StorageType] = mapped_column(
        SAEnum(StorageType, name="storage_type", native_enum=False, length=24),
        default=StorageType.OWN_GODOWN,
        nullable=False,
        index=True,
    )
    capacity_quintal: Mapped[float] = mapped_column(Float, nullable=False)
    occupied_quintal: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    village: Mapped[str | None] = mapped_column(String(120))
    taluka: Mapped[str | None] = mapped_column(String(120), index=True)
    district: Mapped[str | None] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(80), default="Maharashtra")
    pincode: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)
    storage_cost_per_quintal_month: Mapped[float | None] = mapped_column(Float)
    available_from: Mapped[date | None] = mapped_column(Date)
    temperature_controlled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_commodities: Mapped[list] = mapped_column(JSON, default=list)
    amenities: Mapped[list] = mapped_column(JSON, default=list)
    contact_person: Mapped[str | None] = mapped_column(String(160))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner: Mapped[User] = relationship()

    @property
    def available_quintal(self) -> float:
        return max(0.0, self.capacity_quintal - self.occupied_quintal)
