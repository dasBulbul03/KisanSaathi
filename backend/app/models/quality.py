"""Quality inspection records and measured attribute values."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import InspectionStatus, QualityGrade
from app.db.base import JSON, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.catalog import QualityAttribute
    from app.models.trade import FarmLot, Order
    from app.models.user import User


class QualityInspection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "quality_inspections"

    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("farm_lots.id", ondelete="CASCADE"), index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    inspector_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    inspection_type: Mapped[str] = mapped_column(
        String(32), default="PRE_DELIVERY", nullable=False, index=True
    )
    inspected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    grade: Mapped[QualityGrade] = mapped_column(
        SAEnum(QualityGrade, name="inspection_quality_grade", native_enum=False, length=16),
        nullable=False,
        index=True,
    )
    status: Mapped[InspectionStatus] = mapped_column(
        SAEnum(InspectionStatus, name="inspection_status", native_enum=False, length=16),
        default=InspectionStatus.PENDING,
        nullable=False,
        index=True,
    )
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    moisture_percent: Mapped[float | None] = mapped_column(Float)
    damage_percent: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(default=False, nullable=False)

    lot: Mapped[FarmLot] = relationship(back_populates="inspections")
    order: Mapped[Order] = relationship(back_populates="inspections")
    inspector: Mapped[User] = relationship(foreign_keys=[inspector_user_id])
    measurements: Mapped[list[QualityMeasurement]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_quality_inspections_lot", "lot_id", "inspected_at"),)


class QualityMeasurement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "quality_measurements"

    inspection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quality_inspections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quality_attributes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    numeric_value: Mapped[float | None] = mapped_column(Float)
    text_value: Mapped[str | None] = mapped_column(String(200))
    grade_band: Mapped[str | None] = mapped_column(String(16))

    inspection: Mapped[QualityInspection] = relationship(back_populates="measurements")
    attribute: Mapped[QualityAttribute] = relationship(back_populates="measurements")
