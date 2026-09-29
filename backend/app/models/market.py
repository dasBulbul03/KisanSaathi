"""Mandi price and arrival records."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import PriceSource
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.catalog import Commodity, Market


class MarketPrice(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Daily modal/min/max price for a commodity at a market."""

    __tablename__ = "market_prices"

    market_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commodity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commodities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    min_price: Mapped[float] = mapped_column(Float, nullable=False)
    max_price: Mapped[float] = mapped_column(Float, nullable=False)
    modal_price: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    arrivals_quantity: Mapped[float | None] = mapped_column(Float)
    arrivals_unit: Mapped[str] = mapped_column(default="quintal", nullable=False)
    unit: Mapped[str] = mapped_column(default="quintal", nullable=False)
    variety: Mapped[str | None] = mapped_column()
    source: Mapped[PriceSource] = mapped_column(
        SAEnum(PriceSource, name="price_source", native_enum=False, length=24),
        default=PriceSource.DEMO,
        nullable=False,
        index=True,
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    source_reference: Mapped[str | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column()

    market: Mapped[Market] = relationship(back_populates="prices")
    commodity: Mapped[Commodity] = relationship(back_populates="prices")

    __table_args__ = (
        UniqueConstraint("market_id", "commodity_id", "price_date", name="uq_market_price_day"),
        Index("ix_market_prices_lookup", "commodity_id", "price_date"),
        Index("ix_market_prices_market_lookup", "market_id", "commodity_id", "price_date"),
    )


class MarketArrival(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Inward arrival volume, kept separate from the price row so both can be
    refreshed independently by different provider feeds."""

    __tablename__ = "market_arrivals"

    market_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commodity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commodities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    arrival_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(default="quintal", nullable=False)
    vehicle_count: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[PriceSource] = mapped_column(
        SAEnum(PriceSource, name="arrival_price_source", native_enum=False, length=24),
        default=PriceSource.DEMO,
        nullable=False,
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("market_id", "commodity_id", "arrival_date", name="uq_market_arrival_day"),
        Index("ix_market_arrivals_lookup", "commodity_id", "arrival_date"),
    )
