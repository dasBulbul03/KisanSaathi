"""Authentication and user schemas."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.enums import BuyerType, PaymentTerms, UserRole, UserStatus, VerificationStatus

PHONE_RE = re.compile(r"^[6-9]\d{9}$")
GST_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

#: Roles that are onboarded by an administrator and cannot self-register.
STAFF_ONLY_ROLES = frozenset(
    {UserRole.ADMIN, UserRole.QUALITY_INSPECTOR, UserRole.LOGISTICS_PARTNER}
)
#: Roles a member of the public can create for themselves.
SELF_SERVICE_ROLES = frozenset({UserRole.FARMER, UserRole.FPO, UserRole.BUYER})


def validate_indian_phone(value: str) -> str:
    cleaned = re.sub(r"[\s\-()]", "", value or "")
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    if not PHONE_RE.match(cleaned):
        raise ValueError("Enter a valid 10 digit Indian mobile number.")
    return cleaned


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=128)
    role: UserRole
    district: str | None = Field(default=None, max_length=80)
    # role specific onboarding fields
    village: str | None = None
    taluka: str | None = None
    farm_area_acres: float | None = Field(default=None, gt=0, le=10000)
    primary_crops: list[str] = Field(default_factory=list)
    organisation_name: str | None = Field(default=None, max_length=200)
    buyer_type: BuyerType | None = None
    gst_number: str | None = None
    member_count: int | None = Field(default=None, ge=1, le=100000)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return validate_indian_phone(v)

    @field_validator("gst_number")
    @classmethod
    def _gst(cls, v: str | None) -> str | None:
        if v and not GST_RE.match(v.upper()):
            raise ValueError("Enter a valid 15 character GSTIN.")
        return v.upper() if v else None

    @field_validator("role")
    @classmethod
    def _role(cls, v: UserRole) -> UserRole:
        if v not in SELF_SERVICE_ROLES:
            raise ValueError(
                "This role cannot be self-registered. Contact the district "
                "administrator for onboarding."
            )
        return v

    @field_validator("organisation_name")
    @classmethod
    def _org_required(cls, v: str | None, info) -> str | None:
        if info.data.get("role") in (UserRole.BUYER, UserRole.FPO) and not v:
            raise ValueError("Organisation name is required for buyers and FPOs.")
        return v


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=3, description="Registered phone number or email")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("identifier")
    @classmethod
    def _identifier(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v:
            return validate_indian_phone(v)
        return v.lower()


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    expires_at: datetime


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: UserRole
    display_name: str
    description: str
    permissions: list[str]


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None = None
    avatar_url: str | None = None
    district: str | None = None
    state: str = "Maharashtra"
    role: UserRole
    status: UserStatus
    is_email_verified: bool
    is_phone_verified: bool


class FarmerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farmer_id_code: str | None = None
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    state: str = "Maharashtra"
    pincode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    farm_area_acres: float | None = None
    farming_since: date | None = None
    irrigation_source: str | None = None
    primary_crops: list[str] = Field(default_factory=list)
    annual_production_quintal: float | None = None
    storage_available: bool = False
    storage_capacity_quintal: float | None = None
    upi_id: str | None = None
    bank_name: str | None = None
    bank_account_last4: str | None = None
    ifsc_code: str | None = None
    kcc_number: str | None = None


class FPOProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_name: str
    registration_number: str | None = None
    registration_authority: str | None = None
    registration_date: date | None = None
    gst_number: str | None = None
    fpo_type: str | None = None
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    state: str = "Maharashtra"
    latitude: float | None = None
    longitude: float | None = None
    member_count: int = 0
    women_member_count: int = 0
    commodities: list[str] = Field(default_factory=list)
    aggregate_capacity_quintal: float | None = None
    annual_turnover_lakhs: float | None = None
    storage_available: bool = False
    storage_capacity_quintal: float | None = None
    cold_storage_units: int = 0
    contact_person: str | None = None
    contact_phone: str | None = None
    website: str | None = None


class BuyerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_name: str
    buyer_type: BuyerType
    gst_number: str | None = None
    fssai_licence: str | None = None
    verification_status: VerificationStatus
    verified_at: datetime | None = None
    verification_notes: str | None = None
    commodities: list[str] = Field(default_factory=list)
    monthly_volume_quintal: float | None = None
    quality_requirements: list[str] = Field(default_factory=list)
    payment_terms: PaymentTerms = PaymentTerms.NET_7
    default_payment_terms_days: int = 7
    purchasing_locations: list[str] = Field(default_factory=list)
    district: str | None = None
    taluka: str | None = None
    city: str | None = None
    state: str = "Maharashtra"
    latitude: float | None = None
    longitude: float | None = None
    contact_person: str | None = None
    website: str | None = None


class ProfileOut(BaseModel):
    user: UserSummary
    farmer: FarmerProfileOut | None = None
    fpo: FPOProfileOut | None = None
    buyer: BuyerProfileOut | None = None
    permissions: list[str] = Field(default_factory=list)


class FarmerProfileUpdate(BaseModel):
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    pincode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    farm_area_acres: float | None = Field(default=None, gt=0, le=10000)
    farming_since: date | None = None
    irrigation_source: str | None = None
    primary_crops: list[str] | None = None
    annual_production_quintal: float | None = Field(default=None, ge=0)
    storage_available: bool | None = None
    storage_capacity_quintal: float | None = Field(default=None, ge=0)
    upi_id: str | None = None
    bank_name: str | None = None
    bank_account_last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    ifsc_code: str | None = None
    kcc_number: str | None = None

    @field_validator("ifsc_code")
    @classmethod
    def _ifsc(cls, v: str | None) -> str | None:
        if v and not IFSC_RE.match(v.upper()):
            raise ValueError("Enter a valid IFSC code.")
        return v.upper() if v else None


class FPOProfileUpdate(BaseModel):
    organisation_name: str | None = None
    registration_number: str | None = None
    registration_authority: str | None = None
    registration_date: date | None = None
    gst_number: str | None = None
    fpo_type: str | None = None
    village: str | None = None
    taluka: str | None = None
    district: str | None = None
    pincode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    member_count: int | None = Field(default=None, ge=0)
    women_member_count: int | None = Field(default=None, ge=0)
    commodities: list[str] | None = None
    aggregate_capacity_quintal: float | None = Field(default=None, ge=0)
    annual_turnover_lakhs: float | None = Field(default=None, ge=0)
    storage_available: bool | None = None
    storage_capacity_quintal: float | None = Field(default=None, ge=0)
    cold_storage_units: int | None = Field(default=None, ge=0)
    contact_person: str | None = None
    contact_phone: str | None = None
    website: str | None = None

    @field_validator("gst_number")
    @classmethod
    def _gst(cls, v: str | None) -> str | None:
        if v and not GST_RE.match(v.upper()):
            raise ValueError("Enter a valid 15 character GSTIN.")
        return v.upper() if v else None


class BuyerProfileUpdate(BaseModel):
    organisation_name: str | None = None
    buyer_type: BuyerType | None = None
    gst_number: str | None = None
    fssai_licence: str | None = None
    commodities: list[str] | None = None
    monthly_volume_quintal: float | None = Field(default=None, ge=0)
    quality_requirements: list[str] | None = None
    payment_terms: PaymentTerms | None = None
    default_payment_terms_days: int | None = Field(default=None, ge=0, le=180)
    purchasing_locations: list[str] | None = None
    district: str | None = None
    taluka: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    contact_person: str | None = None
    website: str | None = None

    @field_validator("gst_number")
    @classmethod
    def _gst(cls, v: str | None) -> str | None:
        if v and not GST_RE.match(v.upper()):
            raise ValueError("Enter a valid 15 character GSTIN.")
        return v.upper() if v else None


class UserUpdateSelf(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: EmailStr | None = None
    avatar_url: str | None = None
    preferred_language: str | None = Field(default=None, max_length=8)
    district: str | None = None
    farmer: FarmerProfileUpdate | None = None
    fpo: FPOProfileUpdate | None = None
    buyer: BuyerProfileUpdate | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UserListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None = None
    role: UserRole
    status: UserStatus
    district: str | None = None
    taluka: str | None = None
    village: str | None = None
    organisation_name: str | None = None
    verification_status: VerificationStatus | None = None
    created_at: datetime
    last_login_at: datetime | None = None


class UserStatusUpdate(BaseModel):
    status: UserStatus
    reason: str | None = Field(default=None, max_length=255)


class StaffUserCreate(BaseModel):
    """Administrator-onboarded account for roles that cannot self-register."""

    full_name: str = Field(min_length=2, max_length=160)
    phone: str
    email: EmailStr | None = None
    role: UserRole
    password: str = Field(min_length=8, max_length=128)
    district: str | None = Field(default=None, max_length=80)
    organisation_name: str | None = Field(default=None, max_length=200)
    is_active: bool = True

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return validate_indian_phone(v)

    @field_validator("role")
    @classmethod
    def _staff_role(cls, v: UserRole) -> UserRole:
        if v not in STAFF_ONLY_ROLES:
            raise ValueError("Use the public registration endpoint for farmers, FPOs and buyers.")
        return v
