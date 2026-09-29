"""Catalog and market intelligence schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import MarketType, PriceSource, SyncStatus


class CommodityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    name_hindi: str | None = None
    name_marathi: str | None = None
    category: str
    default_unit: str
    permitted_units: list[str] = Field(default_factory=list)
    is_perishable: bool
    shelf_life_days: int | None = None
    seasonality_note: str | None = None
    image_url: str | None = None
    description: str | None = None
    is_active: bool = True


class CommodityCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=2, max_length=40)
    category: str = Field(min_length=2, max_length=80)
    name_hindi: str | None = None
    name_marathi: str | None = None
    default_unit: str = "quintal"
    permitted_units: list[str] = Field(default_factory=lambda: ["quintal", "tonne", "kg"])
    is_perishable: bool = True
    shelf_life_days: int | None = Field(default=None, ge=1, le=365)
    seasonality_note: str | None = None
    description: str | None = None
    min_price_floor: float | None = Field(default=None, ge=0)
    max_price_ceiling: float | None = Field(default=None, ge=0)


class CommodityUpdate(BaseModel):
    name: str | None = None
    name_hindi: str | None = None
    name_marathi: str | None = None
    category: str | None = None
    seasonality_note: str | None = None
    description: str | None = None
    is_perishable: bool | None = None
    shelf_life_days: int | None = Field(default=None, ge=1, le=365)
    is_active: bool | None = None


class QualityAttributeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    commodity_id: uuid.UUID
    code: str
    label: str
    unit: str | None = None
    data_type: str
    min_value: float | None = None
    max_value: float | None = None
    ideal_min: float | None = None
    ideal_max: float | None = None
    grade_a_min: float | None = None
    grade_b_min: float | None = None
    description: str | None = None


class MarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    market_type: MarketType
    district: str
    taluka: str | None = None
    state: str = "Maharashtra"
    address: str | None = None
    pincode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    contact_phone: str | None = None
    apmc_number: str | None = None
    has_storage: bool = False
    has_weighbridge: bool = True
    trading_hours: str | None = None
    is_active: bool = True


class MarketCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    code: str = Field(min_length=2, max_length=40)
    district: str = Field(min_length=2, max_length=80)
    market_type: MarketType = MarketType.APMC_MANDI
    taluka: str | None = None
    state: str = "Maharashtra"
    address: str | None = None
    pincode: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    contact_phone: str | None = None
    apmc_number: str | None = None
    has_storage: bool = False
    trading_hours: str | None = None


class MarketUpdate(BaseModel):
    name: str | None = None
    district: str | None = None
    taluka: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    contact_phone: str | None = None
    has_storage: bool | None = None
    is_active: bool | None = None


class MarketPriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    market_id: uuid.UUID
    market_name: str | None = None
    market_type: MarketType | None = None
    commodity_id: uuid.UUID
    commodity_name: str | None = None
    price_date: date
    min_price: float
    max_price: float
    modal_price: float
    arrivals_quantity: float | None = None
    arrivals_unit: str = "quintal"
    unit: str = "quintal"
    source: PriceSource
    is_demo: bool = True


class MarketPriceTrendPoint(BaseModel):
    date: date
    modal_price: float
    min_price: float
    max_price: float
    arrivals_quantity: float | None = None
    market_count: int = 1


class MarketPriceTrend(BaseModel):
    commodity_id: uuid.UUID
    commodity_name: str
    unit: str = "quintal"
    from_date: date
    to_date: date
    points: list[MarketPriceTrendPoint]
    district_median_modal_price: float | None = None
    overall_change_pct: float | None = None
    is_demo_data: bool = True
    disclaimer: str


class MarketComparisonRow(BaseModel):
    market_id: uuid.UUID
    market_name: str
    district: str
    modal_price: float
    min_price: float
    max_price: float
    arrivals_quantity: float | None = None
    distance_km: float | None = None
    change_pct_7d: float | None = None


class MarketComparison(BaseModel):
    commodity_id: uuid.UUID
    commodity_name: str
    price_date: date
    rows: list[MarketComparisonRow]
    best_market_id: uuid.UUID | None = None
    nearest_market_id: uuid.UUID | None = None
    is_demo_data: bool = True
    disclaimer: str


class MarketArrivalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    market_id: uuid.UUID
    commodity_id: uuid.UUID
    arrival_date: date
    quantity: float
    unit: str
    vehicle_count: int | None = None
    source: PriceSource
    is_demo: bool = True


class MarketDataSyncLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    status: SyncStatus
    started_at: datetime
    finished_at: datetime | None = None
    records_processed: int
    records_inserted: int
    records_updated: int
    message: str | None = None


PRICE_DISCLAIMER = (
    "Mandi prices are indicative reference rates published for information only. "
    "They are not a guaranteed price and are not an offer to buy or sell."
)
