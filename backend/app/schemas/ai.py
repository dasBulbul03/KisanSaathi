"""AI and dashboard schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    AIConversationMode,
    ConfidenceLevel,
    LotStatus,
    OrderStatus,
    PaymentStatus,
    QualityGrade,
)


class AIChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    conversation_id: uuid.UUID | None = None
    commodity_id: uuid.UUID | None = None
    context_district: str | None = None
    language: str = "en"


class AIChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    provider: str
    model: str | None = None
    is_fallback: bool = False
    suggestions: list[str] = Field(default_factory=list)
    data_cards: list[dict] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    disclaimer: str
    created_at: datetime


class AIMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    tool_name: str | None = None
    data: dict | None = None
    provider: str | None = None
    model: str | None = None
    created_at: datetime


class AIConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    mode: AIConversationMode
    total_messages: int
    last_message_at: datetime | None = None
    created_at: datetime
    messages: list[AIMessageOut] = Field(default_factory=list)


class AIFactor(BaseModel):
    code: str
    label: str
    impact: str
    detail: str
    weight: float = 0.0


class SellingWindow(BaseModel):
    start: date | None = None
    end: date | None = None
    label: str
    rationale: str


class MarketSuggestion(BaseModel):
    market_id: uuid.UUID
    market_name: str
    district: str
    modal_price: float
    distance_km: float | None = None
    net_price_after_transport: float | None = None
    rank: int
    reason: str


class PriceDiscoveryResponse(BaseModel):
    commodity_id: uuid.UUID
    commodity_name: str
    unit: str = "quintal"
    current_market_range: tuple[float, float]
    estimated_fair_price_range: tuple[float, float]
    district_modal_price: float | None = None
    price_position_pct: float | None = None
    trend_direction: str
    trend_change_pct: float | None = None
    demand_level: str
    demand_signal: str | None = None
    suggested_markets: list[MarketSuggestion] = Field(default_factory=list)
    selling_window: SellingWindow | None = None
    confidence: ConfidenceLevel
    confidence_score: float
    factors: list[AIFactor] = Field(default_factory=list)
    storage_advice: str | None = None
    transport_estimate: float | None = None
    is_demo_data: bool = True
    generated_at: datetime
    disclaimer: str


class AIRecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    summary: str
    payload: dict = Field(default_factory=dict)
    factors: list = Field(default_factory=list)
    confidence: ConfidenceLevel
    engine: str = "rules"
    model: str | None = None
    provider: str | None = None
    disclaimer: str | None = None
    created_at: datetime


class DashboardStat(BaseModel):
    label: str
    value: float
    display: str
    unit: str | None = None
    change_pct: float | None = None
    trend: str | None = None
    hint: str | None = None


class MarketInsightCard(BaseModel):
    kind: str
    title: str
    message: str
    tone: str = "info"
    action_label: str | None = None
    action_href: str | None = None
    confidence: ConfidenceLevel | None = None


class FarmerDashboard(BaseModel):
    generated_at: datetime
    greeting: str
    seller: dict
    stats: list[DashboardStat]
    price_cards: list[dict]
    insights: list[MarketInsightCard]
    active_lots: list[dict]
    recent_offers: list[dict]
    order_pipeline: list[dict]
    notifications: list[dict]
    ai_recommendation: dict | None = None
    is_demo_data: bool = True


class BuyerDashboard(BaseModel):
    generated_at: datetime
    greeting: str
    buyer: dict
    stats: list[DashboardStat]
    open_demands: list[dict]
    recent_lots: list[dict]
    offers: list[dict]
    orders: list[dict]
    recommended_lots: list[dict]
    notifications: list[dict]
    is_demo_data: bool = True


class AdminDashboard(BaseModel):
    generated_at: datetime
    stats: list[DashboardStat]
    registrations: dict
    trade: dict
    demand_by_commodity: list[dict]
    activity_by_district: list[dict]
    price_movement: list[dict]
    pending_actions: dict
    system_health: dict
    is_demo_data: bool = True


class LotStatusCount(BaseModel):
    status: LotStatus
    count: int


class OrderPipeline(BaseModel):
    status: OrderStatus
    count: int
    value: float


class PaymentSummary(BaseModel):
    total_expected: float
    total_paid: float
    total_pending: float
    overdue_amount: float
    overdue_count: int
    by_status: dict[str, int]
    payment_status: PaymentStatus | None = None


class TrendSeries(BaseModel):
    labels: list[str]
    values: list[float]
    secondary_labels: list[str] | None = None
    secondary_values: list[float] | None = None
    unit: str | None = None
    title: str | None = None


class CommodityDemandStat(BaseModel):
    commodity_id: uuid.UUID
    commodity_name: str
    open_demands: int
    demanded_quintal: float
    active_lots: int
    listed_quintal: float
    median_modal_price: float | None = None
    demand_supply_ratio: float | None = None
    demand_level: str


class DistrictActivityStat(BaseModel):
    district: str
    farmers: int
    fpos: int
    active_lots: int
    trade_value: float
    avg_price: float | None = None
    top_commodity: str | None = None


class GradeDistribution(BaseModel):
    grade: QualityGrade
    lots: int
    quantity: float
