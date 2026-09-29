"""Trade schemas: lots, demands, offers, orders, transactions, matching."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    DemandStatus,
    LotStatus,
    OfferStatus,
    OrderStatus,
    PaymentTerms,
    QualityGrade,
    SellerType,
)


# --------------------------------------------------------------------- lots
class LotImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    caption: str | None = None
    is_primary: bool = False


class LotImageCreate(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    caption: str | None = Field(default=None, max_length=200)
    is_primary: bool = False


class FarmLotCreate(BaseModel):
    commodity_id: uuid.UUID
    title: str = Field(min_length=3, max_length=200)
    quantity: float = Field(gt=0, le=1_000_000)
    unit: str = "quintal"
    quality_grade: QualityGrade = QualityGrade.GRADE_A
    expected_price: float | None = Field(default=None, ge=0)
    minimum_price: float | None = Field(default=None, ge=0)
    harvest_date: date | None = None
    available_from: date | None = None
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    pincode: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    storage_available: bool = False
    organic_certified: bool = False
    pickup_available: bool = True
    seller_handles_transport: bool = True
    quality_specs: dict = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=2000)
    images: list[LotImageCreate] = Field(default_factory=list)
    publish_now: bool = False

    @model_validator(mode="after")
    def _check_prices(self) -> FarmLotCreate:
        if (
            self.minimum_price is not None
            and self.expected_price is not None
            and self.minimum_price > self.expected_price
        ):
            raise ValueError("minimum_price cannot be greater than expected_price.")
        return self


class FarmLotUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    quantity: float | None = Field(default=None, gt=0)
    available_quantity: float | None = Field(default=None, gt=0)
    expected_price: float | None = Field(default=None, ge=0)
    minimum_price: float | None = Field(default=None, ge=0)
    quality_grade: QualityGrade | None = None
    quality_specs: dict | None = None
    harvest_date: date | None = None
    available_from: date | None = None
    storage_available: bool | None = None
    organic_certified: bool | None = None
    pickup_available: bool | None = None
    seller_handles_transport: bool | None = None
    description: str | None = None
    images: list[LotImageCreate] | None = None


class LotSellerOut(BaseModel):
    id: uuid.UUID
    full_name: str
    role: str
    district: str | None = None
    taluka: str | None = None
    village: str | None = None
    organisation_name: str | None = None
    member_count: int | None = None
    phone: str | None = None
    is_verified_seller: bool = False
    completed_orders: int = 0
    rating: float | None = None


class FarmLotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lot_code: str
    seller_type: SellerType
    seller_user_id: uuid.UUID
    commodity_id: uuid.UUID
    commodity_name: str | None = None
    commodity_category: str | None = None
    title: str
    description: str | None = None
    quantity: float
    available_quantity: float
    unit: str
    expected_price: float | None = None
    minimum_price: float | None = None
    quality_grade: QualityGrade
    quality_specs: dict = Field(default_factory=dict)
    harvest_date: date | None = None
    available_from: date | None = None
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    state: str = "Maharashtra"
    latitude: float | None = None
    longitude: float | None = None
    storage_available: bool = False
    organic_certified: bool = False
    pickup_available: bool = True
    seller_handles_transport: bool = True
    status: LotStatus
    published_at: datetime | None = None
    view_count: int = 0
    active_offers_count: int = 0
    created_at: datetime
    updated_at: datetime
    images: list[LotImageOut] = Field(default_factory=list)
    seller: LotSellerOut | None = None
    latest_market_price: float | None = None
    market_price_source_market: str | None = None
    distance_km: float | None = None
    inspection_grade: QualityGrade | None = None


# ------------------------------------------------------------------ demands
class BuyerDemandCreate(BaseModel):
    commodity_id: uuid.UUID
    required_quantity: float = Field(gt=0, le=1_000_000)
    unit: str = "quintal"
    min_grade: QualityGrade = QualityGrade.GRADE_B
    quality_specs: dict = Field(default_factory=dict)
    min_price_per_unit: float | None = Field(default=None, ge=0)
    max_price_per_unit: float | None = Field(default=None, ge=0)
    delivery_location: str = Field(min_length=3, max_length=240)
    district: str | None = None
    taluka: str | None = None
    city: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    max_pickup_radius_km: float = Field(default=250.0, gt=0, le=2000)
    required_by_date: date
    delivery_window_days: int = Field(default=3, ge=0, le=90)
    payment_terms: PaymentTerms = PaymentTerms.NET_7
    payment_terms_days: int = Field(default=7, ge=0, le=180)
    requires_verified_buyer: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class BuyerDemandUpdate(BaseModel):
    required_quantity: float | None = Field(default=None, gt=0)
    min_grade: QualityGrade | None = None
    quality_specs: dict | None = None
    min_price_per_unit: float | None = Field(default=None, ge=0)
    max_price_per_unit: float | None = Field(default=None, ge=0)
    delivery_location: str | None = None
    required_by_date: date | None = None
    payment_terms: PaymentTerms | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=180)
    notes: str | None = None
    status: DemandStatus | None = None


class BuyerDemandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference_code: str
    buyer_user_id: uuid.UUID
    buyer_name: str | None = None
    buyer_organisation: str | None = None
    buyer_verified: bool = False
    commodity_id: uuid.UUID
    commodity_name: str | None = None
    required_quantity: float
    fulfilled_quantity: float = 0.0
    unit: str
    min_grade: QualityGrade
    quality_specs: dict = Field(default_factory=dict)
    min_price_per_unit: float | None = None
    max_price_per_unit: float | None = None
    delivery_location: str
    district: str | None = None
    taluka: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    max_pickup_radius_km: float = 250.0
    required_by_date: date
    delivery_window_days: int = 3
    payment_terms: PaymentTerms = PaymentTerms.NET_7
    payment_terms_days: int = 7
    requires_verified_buyer: bool = False
    status: DemandStatus
    notes: str | None = None
    active_offers_count: int = 0
    matched_lots_count: int = 0
    created_at: datetime


# ------------------------------------------------------------------- offers
class OfferCreate(BaseModel):
    lot_id: uuid.UUID
    demand_id: uuid.UUID | None = None
    offered_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    unit: str = "quintal"
    delivery_terms: str | None = Field(default=None, max_length=200)
    payment_terms: PaymentTerms = PaymentTerms.NET_7
    payment_terms_days: int = Field(default=7, ge=0, le=180)
    valid_until: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)


class OfferCounter(BaseModel):
    offered_price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    unit: str = "quintal"
    delivery_terms: str | None = Field(default=None, max_length=200)
    payment_terms: PaymentTerms | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=180)
    valid_until: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)


class OfferReject(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference_code: str
    lot_id: uuid.UUID
    lot_code: str | None = None
    lot_title: str | None = None
    commodity_id: uuid.UUID | None = None
    commodity_name: str | None = None
    buyer_user_id: uuid.UUID
    buyer_name: str | None = None
    buyer_organisation: str | None = None
    buyer_verified: bool = False
    demand_id: uuid.UUID | None = None
    offered_price: float
    quantity: float
    unit: str
    delivery_terms: str | None = None
    payment_terms: PaymentTerms = PaymentTerms.NET_7
    payment_terms_days: int = 7
    valid_until: datetime | None = None
    notes: str | None = None
    status: OfferStatus
    parent_offer_id: uuid.UUID | None = None
    responded_at: datetime | None = None
    decline_reason: str | None = None
    total_value: float | None = None
    created_at: datetime
    is_buyer: bool = False
    is_seller: bool = False
    can_respond: bool = False


# ------------------------------------------------------------------- orders
class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_number: str
    offer_id: uuid.UUID
    lot_id: uuid.UUID
    lot_code: str | None = None
    buyer_user_id: uuid.UUID
    buyer_name: str | None = None
    buyer_organisation: str | None = None
    seller_user_id: uuid.UUID
    seller_name: str | None = None
    seller_organisation: str | None = None
    commodity_id: uuid.UUID
    commodity_name: str | None = None
    quantity: float
    unit: str
    agreed_price: float
    total_value: float
    quality_grade: QualityGrade
    status: OrderStatus
    pickup_location: str
    pickup_district: str | None = None
    delivery_location: str
    delivery_district: str | None = None
    pickup_date: date | None = None
    delivery_date: date | None = None
    payment_terms_days: int = 7
    status_history: list = Field(default_factory=list)
    cancelled_reason: str | None = None
    logistics_status: str | None = None
    logistics_reference: str | None = None
    payment_status: str | None = None
    payment_due_date: date | None = None
    created_at: datetime
    updated_at: datetime


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    note: str | None = Field(default=None, max_length=255)
    pickup_date: date | None = None
    delivery_date: date | None = None
    reason: str | None = Field(default=None, max_length=255)


# ------------------------------------------------------------- transactions
class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_reference: str
    order_id: uuid.UUID
    order_number: str | None = None
    seller_user_id: uuid.UUID
    seller_name: str | None = None
    buyer_user_id: uuid.UUID
    buyer_name: str | None = None
    commodity_id: uuid.UUID
    commodity_name: str | None = None
    quantity: float
    unit: str
    unit_price: float
    total_amount: float
    platform_fee: float = 0.0
    status: OrderStatus
    district: str | None = None
    initiated_at: datetime
    completed_at: datetime | None = None
    payment_status: str | None = None
    amount_paid: float = 0.0


# ----------------------------------------------------------------- matching
class MatchReason(BaseModel):
    code: str
    label: str
    satisfied: bool
    weight: float
    detail: str | None = None


class MatchResult(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    reference_code: str | None = None
    title: str
    score: float = Field(ge=0, le=100)
    score_label: str
    commodity: str | None = None
    quantity: float | None = None
    unit: str | None = None
    grade: QualityGrade | None = None
    expected_price: float | None = None
    price_range: tuple[float, float] | None = None
    district: str | None = None
    location: str | None = None
    distance_km: float | None = None
    is_verified_buyer: bool = False
    seller_name: str | None = None
    seller_organisation: str | None = None
    completed_orders: int = 0
    rating: float | None = None
    required_by_date: date | None = None
    available_from: date | None = None
    reasons: list[MatchReason] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str


MATCH_DISCLAIMER = (
    "Match scores compare your stated requirements against available supply using the "
    "data available on the platform. They are a decision aid, not a guarantee of trade."
)


class MatchSummary(BaseModel):
    direction: str
    total_candidates: int
    strong_matches: int
    generated_at: datetime
    disclaimer: str = MATCH_DISCLAIMER
