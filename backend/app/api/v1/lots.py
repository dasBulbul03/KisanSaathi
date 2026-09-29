"""Farm lot (seller inventory) endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    CurrentSeller,
    CurrentUser,
    DbSession,
    OptionalUser,
    Pagination,
    require_permissions,
)
from app.core.enums import LotStatus, UserRole
from app.core.rbac import LOT_CANCEL, LOT_CREATE, LOT_PUBLISH, LOT_UPDATE_OWN
from app.models import User
from app.schemas.common import Page, PageParams
from app.schemas.trade import FarmLotCreate, FarmLotOut, FarmLotUpdate, MatchResult
from app.services.lot_service import LotService
from app.services.matching_service import MatchingService

router = APIRouter(prefix="/lots", tags=["lots"])

LotCreator = Annotated[User, Depends(require_permissions(LOT_CREATE))]
LotUpdater = Annotated[User, Depends(require_permissions(LOT_UPDATE_OWN))]
LotPublisher = Annotated[User, Depends(require_permissions(LOT_PUBLISH))]
LotCanceller = Annotated[User, Depends(require_permissions(LOT_CANCEL))]


def _lot_out(service: LotService, lot: object) -> FarmLotOut:
    """Serialise a lot with the enriched marketplace fields."""
    return FarmLotOut.model_validate(service.enrich(lot))


@router.get("", response_model=Page[FarmLotOut], summary="Browse lots")
def list_lots(
    session: DbSession,
    params: Pagination,
    user: OptionalUser,
    seller_user_id: uuid.UUID | None = Query(None, description="Filter by seller"),
    status_list: list[LotStatus] | None = Query(
        None, alias="status", description="Restrict to these lot statuses"
    ),
    commodity_id: uuid.UUID | None = Query(None, description="Filter by commodity"),
    district: str | None = Query(None, description="Filter by district"),
    taluka: str | None = Query(None, description="Filter by taluka"),
    min_grade: str | None = Query(None, description="Minimum quality grade"),
    available_from: date | None = Query(None, description="Available on or after"),
    available_to: date | None = Query(None, description="Available on or before"),
    min_quantity: float | None = Query(None, description="Minimum available quantity"),
    max_price: float | None = Query(None, description="Maximum expected price"),
    term: str | None = Query(None, description="Free-text search term"),
    organic_only: bool = False,
    exclude_seller_id: uuid.UUID | None = Query(None, description="Exclude a seller's lots"),
    sort: str = "-created_at",
) -> Page[FarmLotOut]:
    """Browse the marketplace.

    Signed-in sellers automatically have their own lots filtered out so they
    see what buyers see; anonymous visitors get an unfiltered public view.
    """
    service = LotService(session)
    exclude = None if user is None else exclude_seller_id
    if user is not None and user.role in (UserRole.FARMER, UserRole.FPO):
        exclude = user.id
    items, total = service.list_lots(
        seller_user_id=seller_user_id,
        status=status_list,
        commodity_id=commodity_id,
        district=district,
        taluka=taluka,
        min_grade=min_grade,
        available_from=available_from,
        available_to=available_to,
        min_quantity=min_quantity,
        max_price=max_price,
        term=term,
        organic_only=organic_only,
        exclude_seller_id=exclude,
        sort=sort,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[FarmLotOut].build([_lot_out(service, lot) for lot in items], total, params)


@router.get("/mine", response_model=Page[FarmLotOut], summary="List own lots")
def my_lots(session: DbSession, params: Pagination, user: CurrentSeller) -> Page[FarmLotOut]:
    """All of the caller's lots across every status, most recent first."""
    service = LotService(session)
    items, total = service.list_lots(
        seller_user_id=user.id, page=params.page, page_size=params.page_size
    )
    return Page[FarmLotOut].build([_lot_out(service, lot) for lot in items], total, params)


@router.get("/stats", response_model=dict[LotStatus, int], summary="Lot status counts")
def lot_stats(session: DbSession, user: CurrentSeller) -> dict[LotStatus, int]:
    """Count of the caller's lots broken down by status (draft, live, sold...)."""
    return LotService(session).status_counts(user.id)


@router.post(
    "",
    response_model=FarmLotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a lot",
)
def create_lot(payload: FarmLotCreate, session: DbSession, user: LotCreator) -> FarmLotOut:
    """Draft a new lot, or publish it immediately when ``publish_now`` is set."""
    service = LotService(session)
    lot = service.create_lot(payload, user)
    session.commit()
    return _lot_out(service, lot)


@router.get("/{lot_id}", response_model=FarmLotOut, summary="Lot detail")
def get_lot(lot_id: uuid.UUID, session: DbSession, user: CurrentUser) -> FarmLotOut:
    """Return a single lot with market price and seller context, and bump its views."""
    service = LotService(session)
    lot = service.get_lot(lot_id)
    service.increment_views(lot_id)
    session.commit()
    return _lot_out(service, lot)


@router.patch("/{lot_id}", response_model=FarmLotOut, summary="Update a lot")
def update_lot(
    lot_id: uuid.UUID, payload: FarmLotUpdate, session: DbSession, user: LotUpdater
) -> FarmLotOut:
    """Edit only the caller's own lots while they are still editable."""
    service = LotService(session)
    lot = service.update_lot(lot_id, payload, user)
    session.commit()
    return _lot_out(service, lot)


@router.post("/{lot_id}/publish", response_model=FarmLotOut, summary="Publish a draft lot")
def publish_lot(lot_id: uuid.UUID, session: DbSession, user: LotPublisher) -> FarmLotOut:
    """Make a draft lot visible to buyers."""
    service = LotService(session)
    lot = service.publish_lot(lot_id, user)
    session.commit()
    return _lot_out(service, lot)


@router.post("/{lot_id}/cancel", response_model=FarmLotOut, summary="Cancel a lot")
def cancel_lot(
    lot_id: uuid.UUID,
    session: DbSession,
    user: LotCanceller,
    reason: str | None = Query(None, max_length=255),
) -> FarmLotOut:
    """Withdraw a lot; pending offers on it are rejected."""
    service = LotService(session)
    lot = service.cancel_lot(lot_id, user, reason=reason)
    session.commit()
    return _lot_out(service, lot)


@router.delete(
    "/{lot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete a lot",
)
def delete_lot(lot_id: uuid.UUID, session: DbSession, user: LotCanceller) -> Response:
    """Permanently delete the caller's own lot while it has no active offers."""
    service = LotService(session)
    service.delete_lot(lot_id, user)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{lot_id}/similar", response_model=Page[FarmLotOut], summary="Similar lots")
def similar_lots(
    lot_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    limit: int = Query(6, ge=1, le=50),
) -> Page[FarmLotOut]:
    """Neighbouring active lots for the same produce."""
    service = LotService(session)
    items = service.similar_lots(lot_id, limit=limit)
    params = PageParams(page=1, page_size=limit)
    return Page[FarmLotOut].build([_lot_out(service, lot) for lot in items], len(items), params)


@router.get(
    "/{lot_id}/matches",
    response_model=list[MatchResult],
    summary="Demands matching a lot",
)
def lot_matches(
    lot_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
) -> list[MatchResult]:
    """Ranked buyer demands that fit this lot, scored from most compatible first."""
    lot = LotService(session).get_lot(lot_id)
    return MatchingService(session).match_lot_to_demands(lot, commodity=lot.commodity, limit=limit)


__all__ = ["router"]
