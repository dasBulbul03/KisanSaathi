"""Storage facility listing and management endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    CurrentSeller,
    CurrentUser,
    DbSession,
    OptionalUser,
    Pagination,
    require_permissions,
)
from app.core.rbac import STORAGE_MANAGE_OWN
from app.models import User
from app.schemas.common import Page
from app.schemas.operations import (
    StorageFacilityCreate,
    StorageFacilityOut,
    StorageFacilityUpdate,
)
from app.services.storage_service import StorageService

router = APIRouter(prefix="/storage", tags=["storage"])

StorageManager = Annotated[User, Depends(require_permissions(STORAGE_MANAGE_OWN))]


def _facility_out(
    service: StorageService, facility: object, viewer: User | None
) -> StorageFacilityOut:
    """Serialise a facility with its owner name and free capacity."""
    return StorageFacilityOut.model_validate(service.enrich(facility, user=viewer))


@router.get("", response_model=Page[StorageFacilityOut], summary="Browse storage")
def list_storage(
    session: DbSession,
    params: Pagination,
    user: OptionalUser,
    owner_user_id: uuid.UUID | None = Query(None, description="Filter by owner"),
    district: str | None = Query(None, description="Filter by district"),
    commodity_name: str | None = Query(
        None, description="Only facilities declaring support for this commodity"
    ),
    min_available_quintal: float | None = Query(
        None, ge=0, description="Minimum free capacity in quintal"
    ),
    temperature_controlled: bool | None = Query(
        None, description="Cold storage only, or false for ambient only"
    ),
    include_private: bool | None = Query(
        None,
        description="Include the caller's own private listings; defaults to true when signed in",
    ),
    origin_latitude: float | None = Query(
        None, ge=-90, le=90, description="Caller latitude for distance ranking"
    ),
    origin_longitude: float | None = Query(
        None, ge=-180, le=180, description="Caller longitude for distance ranking"
    ),
) -> Page[StorageFacilityOut]:
    """Browse godowns and cold stores with their free capacity.

    Private listings are surfaced by default to signed-in callers so a seller
    always finds their own godown in the results, but only *their own* private
    rows are ever returned - another owner's private godown stays hidden because
    it carries their contact details. Pass ``include_private=false`` to force
    the public-only view, which is what anonymous visitors get.
    """
    service = StorageService(session)
    show_private = include_private if include_private is not None else user is not None
    items, total = service.list_facilities(
        owner_user_id=owner_user_id,
        district=district,
        commodity_name=commodity_name,
        min_available_quintal=min_available_quintal,
        temperature_controlled=temperature_controlled,
        include_private=show_private,
        viewer_user_id=user.id if user else None,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[StorageFacilityOut].build(
        [_facility_out(service, facility, user) for facility in items], total, params
    )


@router.get(
    "/options",
    response_model=list[dict[str, Any]],
    summary="Storage options for a seller",
)
def storage_options(
    session: DbSession,
    user: CurrentSeller,
    commodity_name: str | None = Query(None, description="Commodity to be stored"),
    min_available_quintal: float | None = Query(
        None, ge=0, description="Minimum free capacity in quintal"
    ),
) -> list[dict[str, Any]]:
    """Storage a seller can book for a lot: their own first, then the district's.

    Returned in the service's enriched shape so the storage-type label and the
    distance from the seller's district both survive.
    """
    return StorageService(session).options_for_seller(
        user=user,
        commodity_name=commodity_name,
        min_available_quintal=min_available_quintal,
    )


@router.get("/mine", response_model=Page[StorageFacilityOut], summary="List own storage")
def my_storage(
    session: DbSession, params: Pagination, user: CurrentSeller
) -> Page[StorageFacilityOut]:
    """The caller's own facilities, private ones included."""
    service = StorageService(session)
    items, total = service.list_facilities(
        owner_user_id=user.id,
        include_private=True,
        viewer_user_id=user.id,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[StorageFacilityOut].build(
        [_facility_out(service, facility, user) for facility in items], total, params
    )


@router.post(
    "",
    response_model=StorageFacilityOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a storage facility",
)
def create_storage(
    payload: StorageFacilityCreate, session: DbSession, user: StorageManager
) -> StorageFacilityOut:
    """Register a godown or cold store owned by the caller.

    Missing coordinates fall back to the centre of the facility's district so
    distance search still works.
    """
    service = StorageService(session)
    facility = service.create(payload, user)
    session.commit()
    return _facility_out(service, facility, user)


@router.get(
    "/{facility_id}",
    response_model=StorageFacilityOut,
    summary="Storage facility detail",
)
def get_storage(
    facility_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> StorageFacilityOut:
    """A single facility with free capacity and the caller's distance to it."""
    service = StorageService(session)
    return _facility_out(service, service.get(facility_id), user)


@router.patch("/{facility_id}", response_model=StorageFacilityOut, summary="Update a facility")
def update_storage(
    facility_id: uuid.UUID,
    payload: StorageFacilityUpdate,
    session: DbSession,
    user: StorageManager,
) -> StorageFacilityOut:
    """Edit capacity, occupancy, amenities or visibility of a facility.

    Only the owner or an admin may edit, and occupancy may never exceed the
    stated capacity.
    """
    service = StorageService(session)
    facility = service.update(facility_id, payload, user)
    session.commit()
    return _facility_out(service, facility, user)


@router.delete(
    "/{facility_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a facility",
)
def delete_storage(facility_id: uuid.UUID, session: DbSession, user: StorageManager) -> Response:
    """Remove one of the caller's own facilities."""
    service = StorageService(session)
    service.delete(facility_id, user)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
