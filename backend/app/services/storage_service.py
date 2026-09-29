"""Storage facility service."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import StorageType, UserRole
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.models import StorageFacility, User
from app.repositories.operations import StorageRepository
from app.schemas.operations import StorageFacilityCreate, StorageFacilityUpdate
from app.services.audit_service import AuditService
from app.utils.geo import district_coords, haversine_km

logger = get_logger(__name__)

STORAGE_LABELS: dict[StorageType, str] = {
    StorageType.OWN_GODOWN: "Own godown",
    StorageType.RENTED_GODOWN: "Rented godown",
    StorageType.FPO_STORE: "FPO storage",
    StorageType.COLD_STORAGE: "Cold storage",
    StorageType.OPEN_STORAGE: "Open storage",
}


class StorageService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = StorageRepository(StorageFacility, session)
        self.audit = AuditService(session)

    def get(self, facility_id: uuid.UUID) -> StorageFacility:
        facility = self.repo.get(facility_id)
        if facility is None or facility.is_deleted:
            raise NotFoundError(
                "The storage facility could not be found.", code="STORAGE_NOT_FOUND"
            )
        return facility

    def list_facilities(
        self,
        *,
        owner_user_id: uuid.UUID | None = None,
        district: str | None = None,
        commodity_name: str | None = None,
        min_available_quintal: float | None = None,
        temperature_controlled: bool | None = None,
        include_private: bool = False,
        viewer_user_id: uuid.UUID | None = None,
        origin_latitude: float | None = None,
        origin_longitude: float | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[StorageFacility], int]:
        stmt = self.repo.search_query(
            owner_user_id=owner_user_id,
            district=district,
            commodity_name=commodity_name,
            min_available_quintal=min_available_quintal,
            temperature_controlled=temperature_controlled,
            include_private=include_private,
            viewer_user_id=viewer_user_id,
        )
        rows, total = self.repo.paginate(stmt=stmt, page=page, page_size=page_size)
        if origin_latitude is not None and origin_longitude is not None:
            rows.sort(
                key=lambda facility: haversine_km(
                    origin_latitude, origin_longitude, facility.latitude, facility.longitude
                )
            )
        return rows, total

    def create(self, payload: StorageFacilityCreate, user: User) -> StorageFacility:
        lat, lon = payload.latitude, payload.longitude
        if lat is None or lon is None:
            c_lat, c_lon = district_coords(payload.district or user.district)
            lat, lon = lat if lat is not None else c_lat, lon if lon is not None else c_lon
        facility = StorageFacility(
            owner_user_id=user.id,
            name=payload.name.strip(),
            storage_type=payload.storage_type,
            capacity_quintal=payload.capacity_quintal,
            occupied_quintal=payload.occupied_quintal,
            district=payload.district or user.district,
            village=payload.village,
            taluka=payload.taluka,
            pincode=payload.pincode,
            latitude=lat,
            longitude=lon,
            storage_cost_per_quintal_month=payload.storage_cost_per_quintal_month,
            available_from=payload.available_from or date.today(),
            temperature_controlled=payload.temperature_controlled,
            supports_commodities=payload.supports_commodities or [],
            amenities=payload.amenities or [],
            contact_person=payload.contact_person,
            contact_phone=payload.contact_phone,
            is_private=payload.is_private,
            is_active=True,
        )
        self.session.add(facility)
        self.session.flush()
        self.audit.record(
            action="STORAGE_CREATED",
            entity_type="storage_facility",
            entity_id=facility.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={"name": facility.name, "capacity_quintal": facility.capacity_quintal},
        )
        return facility

    def update(
        self, facility_id: uuid.UUID, payload: StorageFacilityUpdate, user: User
    ) -> StorageFacility:
        facility = self.get(facility_id)
        if facility.owner_user_id != user.id and user.role is not UserRole.ADMIN:
            raise PermissionDeniedError(
                "You can only update your own storage facilities.", code="STORAGE_NOT_OWNER"
            )
        data = payload.model_dump(exclude_unset=True)
        if (
            data.get("capacity_quintal") is not None
            and data.get("occupied_quintal", facility.occupied_quintal) > data["capacity_quintal"]
        ):
            from app.core.exceptions import ConflictError

            raise ConflictError(
                "Occupied quantity cannot exceed the new capacity.", code="STORAGE_OCCUPANCY"
            )
        before = {
            "capacity_quintal": facility.capacity_quintal,
            "occupied_quintal": facility.occupied_quintal,
        }
        for key, value in data.items():
            if hasattr(facility, key):
                setattr(facility, key, value)
        self.session.flush()
        self.audit.record(
            action="STORAGE_UPDATED",
            entity_type="storage_facility",
            entity_id=facility.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before=before,
            after={
                "capacity_quintal": facility.capacity_quintal,
                "occupied_quintal": facility.occupied_quintal,
            },
        )
        return facility

    def delete(self, facility_id: uuid.UUID, user: User) -> None:
        facility = self.get(facility_id)
        if facility.owner_user_id != user.id and user.role is not UserRole.ADMIN:
            raise PermissionDeniedError(
                "You can only remove your own storage facilities.", code="STORAGE_NOT_OWNER"
            )
        self.repo.delete(facility)
        self.audit.record(
            action="STORAGE_DELETED",
            entity_type="storage_facility",
            entity_id=facility.id,
            actor_user_id=user.id,
            actor_role=user.role,
        )

    def options_for_seller(
        self,
        *,
        user: User,
        commodity_name: str | None = None,
        min_available_quintal: float | None = None,
    ) -> list[dict[str, Any]]:
        """Own facilities first, then public ones in the same district."""
        own, _ = self.list_facilities(
            owner_user_id=user.id,
            commodity_name=commodity_name,
            min_available_quintal=min_available_quintal,
            include_private=True,
            # Without the viewer id the repository falls back to the public-only
            # branch, which would hide the seller's own private godown from the
            # very list meant to show it first.
            viewer_user_id=user.id,
        )
        public, _ = self.list_facilities(
            district=user.district,
            commodity_name=commodity_name,
            min_available_quintal=min_available_quintal,
            include_private=False,
        )
        seen = {f.id for f in own}
        combined = own + [f for f in public if f.id not in seen]
        return [self.enrich(f, user=user) for f in combined]

    def enrich(
        self,
        facility: StorageFacility,
        *,
        user: User | None = None,
    ) -> dict[str, Any]:
        distance = None
        if user is not None and facility.latitude is not None:
            c_lat, c_lon = district_coords(user.district)
            if c_lat is not None:
                distance = haversine_km(
                    c_lat, c_lon or 0.0, facility.latitude, facility.longitude or 0.0
                )
        return {
            "id": facility.id,
            "owner_user_id": facility.owner_user_id,
            "owner_name": facility.owner.full_name if facility.owner else None,
            "name": facility.name,
            "storage_type": facility.storage_type,
            "capacity_quintal": facility.capacity_quintal,
            "occupied_quintal": facility.occupied_quintal,
            "available_quintal": facility.available_quintal,
            "village": facility.village,
            "taluka": facility.taluka,
            "district": facility.district,
            "state": facility.state,
            "latitude": facility.latitude,
            "longitude": facility.longitude,
            "storage_cost_per_quintal_month": facility.storage_cost_per_quintal_month,
            "available_from": facility.available_from,
            "temperature_controlled": facility.temperature_controlled,
            "supports_commodities": facility.supports_commodities or [],
            "amenities": facility.amenities or [],
            "contact_person": facility.contact_person,
            "contact_phone": facility.contact_phone,
            "is_active": facility.is_active,
            "is_private": facility.is_private,
            "storage_type_label": STORAGE_LABELS.get(
                facility.storage_type, facility.storage_type.value
            ),
            "distance_km": distance,
        }
