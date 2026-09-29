"""Quality, logistics, storage, payment and grievance schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    GrievanceCategory,
    GrievanceStatus,
    InspectionStatus,
    LogisticsStatus,
    PaymentMethod,
    PaymentStatus,
    Priority,
    QualityGrade,
    StorageType,
    VehicleType,
)


# ------------------------------------------------------------------ quality
class QualityMeasurementInput(BaseModel):
    attribute_id: uuid.UUID
    numeric_value: float | None = None
    text_value: str | None = None

    @model_validator(mode="after")
    def _one_value(self) -> QualityMeasurementInput:
        if self.numeric_value is None and not self.text_value:
            raise ValueError("Provide either numeric_value or text_value.")
        return self


class QualityInspectionCreate(BaseModel):
    lot_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    grade: QualityGrade
    inspection_type: str = "PRE_DELIVERY"
    inspected_at: datetime | None = None
    attributes: dict = Field(default_factory=dict)
    measurements: list[QualityMeasurementInput] = Field(default_factory=list)
    moisture_percent: float | None = Field(default=None, ge=0, le=100)
    damage_percent: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _target(self) -> QualityInspectionCreate:
        if not self.lot_id and not self.order_id:
            raise ValueError("An inspection must reference a lot or an order.")
        return self


class QualityMeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attribute_id: uuid.UUID
    attribute_label: str | None = None
    attribute_unit: str | None = None
    numeric_value: float | None = None
    text_value: str | None = None
    grade_band: str | None = None


class QualityInspectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lot_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    inspector_user_id: uuid.UUID | None = None
    inspector_name: str | None = None
    inspection_type: str
    inspected_at: datetime
    grade: QualityGrade
    status: InspectionStatus
    attributes: dict = Field(default_factory=dict)
    moisture_percent: float | None = None
    damage_percent: float | None = None
    notes: str | None = None
    is_demo: bool = False
    created_at: datetime
    measurements: list[QualityMeasurementOut] = Field(default_factory=list)


# ----------------------------------------------------------------- logistics
class LogisticsQuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_name: str
    source: str = "demo"
    vehicle_type: VehicleType
    base_rate: float
    per_km_rate: float
    per_quintal_rate: float
    min_charge: float
    transit_days: int
    cold_chain_surcharge: float
    rating: float
    is_demo: bool = True


class LogisticsQuoteRequest(BaseModel):
    origin_district: str
    destination_district: str
    quantity: float = Field(gt=0)
    unit: str = "quintal"
    cold_chain_required: bool = False


class LogisticsQuoteOption(BaseModel):
    provider_name: str
    vehicle_type: VehicleType
    distance_km: float
    estimated_cost: float
    transit_days: int
    rating: float
    is_demo: bool = True
    note: str | None = None


class LogisticsCreate(BaseModel):
    order_id: uuid.UUID
    provider_user_id: uuid.UUID | None = None
    vehicle_type: VehicleType = VehicleType.TEMPO
    pickup_date: date | None = None
    delivery_date: date | None = None
    transporter_name: str | None = Field(default=None, max_length=160)
    transporter_contact: str | None = Field(default=None, max_length=20)
    estimated_cost: float | None = Field(default=None, ge=0)
    cold_chain_required: bool = False
    notes: str | None = Field(default=None, max_length=1000)


class LogisticsUpdate(BaseModel):
    status: LogisticsStatus | None = None
    vehicle_number: str | None = Field(default=None, max_length=24)
    transporter_name: str | None = Field(default=None, max_length=160)
    transporter_contact: str | None = Field(default=None, max_length=20)
    estimated_cost: float | None = Field(default=None, ge=0)
    actual_cost: float | None = Field(default=None, ge=0)
    pickup_date: date | None = None
    delivery_date: date | None = None
    tracking_number: str | None = Field(default=None, max_length=80)
    notes: str | None = None


class LogisticsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference_code: str
    order_id: uuid.UUID
    order_number: str | None = None
    commodity_name: str | None = None
    provider_user_id: uuid.UUID | None = None
    provider_name: str | None = None
    status: LogisticsStatus
    pickup_location: str
    pickup_district: str | None = None
    destination: str
    destination_district: str | None = None
    distance_km: float | None = None
    quantity: float
    unit: str
    vehicle_type: VehicleType
    vehicle_number: str | None = None
    estimated_cost: float | None = None
    actual_cost: float | None = None
    transporter_name: str | None = None
    transporter_contact: str | None = None
    pickup_date: date | None = None
    delivery_date: date | None = None
    tracking_number: str | None = None
    cold_chain_required: bool = False
    status_history: list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ storage
class StorageFacilityCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    storage_type: StorageType = StorageType.OWN_GODOWN
    capacity_quintal: float = Field(gt=0, le=10_000_000)
    occupied_quintal: float = Field(default=0, ge=0)
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    pincode: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    storage_cost_per_quintal_month: float | None = Field(default=None, ge=0)
    available_from: date | None = None
    temperature_controlled: bool = False
    supports_commodities: list[str] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    contact_person: str | None = None
    contact_phone: str | None = None
    is_private: bool = True

    @model_validator(mode="after")
    def _occupancy(self) -> StorageFacilityCreate:
        if self.occupied_quintal > self.capacity_quintal:
            raise ValueError("occupied_quintal cannot exceed capacity_quintal.")
        return self


class StorageFacilityUpdate(BaseModel):
    name: str | None = None
    storage_type: StorageType | None = None
    capacity_quintal: float | None = Field(default=None, gt=0)
    occupied_quintal: float | None = Field(default=None, ge=0)
    storage_cost_per_quintal_month: float | None = Field(default=None, ge=0)
    available_from: date | None = None
    temperature_controlled: bool | None = None
    supports_commodities: list[str] | None = None
    amenities: list[str] | None = None
    contact_person: str | None = None
    contact_phone: str | None = None
    is_active: bool | None = None
    is_private: bool | None = None


class StorageFacilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_user_id: uuid.UUID
    owner_name: str | None = None
    name: str
    storage_type: StorageType
    capacity_quintal: float
    occupied_quintal: float
    available_quintal: float
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    state: str = "Maharashtra"
    latitude: float | None = None
    longitude: float | None = None
    storage_cost_per_quintal_month: float | None = None
    available_from: date | None = None
    temperature_controlled: bool = False
    supports_commodities: list[str] = Field(default_factory=list)
    amenities: list[str] = Field(default_factory=list)
    contact_person: str | None = None
    contact_phone: str | None = None
    is_active: bool = True
    is_private: bool = True
    distance_km: float | None = None


# ----------------------------------------------------------------- payments
class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_id: uuid.UUID
    transaction_reference: str | None = None
    order_id: uuid.UUID | None = None
    order_number: str | None = None
    payer_user_id: uuid.UUID
    payer_name: str | None = None
    payee_user_id: uuid.UUID
    payee_name: str | None = None
    amount: float
    currency: str = "INR"
    status: PaymentStatus
    method: PaymentMethod
    due_date: date | None = None
    reference_number: str | None = None
    initiated_at: datetime | None = None
    paid_at: datetime | None = None
    failure_reason: str | None = None
    notes: str | None = None
    is_demo: bool = False
    created_at: datetime


class PaymentUpdate(BaseModel):
    status: PaymentStatus
    reference_number: str | None = Field(default=None, max_length=120)
    method: PaymentMethod | None = None
    paid_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)
    failure_reason: str | None = Field(default=None, max_length=255)


# --------------------------------------------------------------- grievances
class GrievanceCreate(BaseModel):
    category: GrievanceCategory
    subject: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10, max_length=4000)
    order_id: uuid.UUID | None = None
    transaction_id: uuid.UUID | None = None
    against_user_id: uuid.UUID | None = None
    priority: Priority = Priority.MEDIUM
    evidence: list[str] = Field(default_factory=list, max_length=10)


class GrievanceUpdate(BaseModel):
    status: GrievanceStatus | None = None
    priority: Priority | None = None
    assigned_to_user_id: uuid.UUID | None = None
    resolution: str | None = Field(default=None, max_length=4000)


class GrievanceCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    is_internal: bool = False


class GrievanceCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    grievance_id: uuid.UUID
    author_user_id: uuid.UUID
    author_name: str | None = None
    author_role: str | None = None
    body: str
    is_internal: bool
    created_at: datetime


class GrievanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_number: str
    raised_by_user_id: uuid.UUID
    raised_by_name: str | None = None
    against_user_id: uuid.UUID | None = None
    against_name: str | None = None
    order_id: uuid.UUID | None = None
    order_number: str | None = None
    transaction_id: uuid.UUID | None = None
    category: GrievanceCategory
    subject: str
    description: str
    status: GrievanceStatus
    priority: Priority
    assigned_to_user_id: uuid.UUID | None = None
    assigned_to_name: str | None = None
    resolution: str | None = None
    resolved_at: datetime | None = None
    due_date: date | None = None
    status_history: list = Field(default_factory=list)
    comment_count: int = 0
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------- notifications
class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    notification_type: str
    data: dict = Field(default_factory=dict)
    is_read: bool
    read_at: datetime | None = None
    link: str | None = None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread_count: int


# ---------------------------------------------------------------- audit log
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    request_id: str | None = None
    ip_address: str | None = None
    note: str | None = None
    before_state: dict | None = None
    after_state: dict | None = None
    created_at: datetime
