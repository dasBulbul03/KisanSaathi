"""Buyer demand (purchase requirement) endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentBuyer,
    CurrentUser,
    DbSession,
    OptionalUser,
    Pagination,
    require_permissions,
)
from app.core.enums import DemandStatus
from app.core.rbac import DEMAND_CREATE, DEMAND_UPDATE_OWN
from app.models import User
from app.schemas.common import Page
from app.schemas.trade import (
    BuyerDemandCreate,
    BuyerDemandOut,
    BuyerDemandUpdate,
    MatchResult,
)
from app.services.demand_service import DemandService
from app.services.matching_service import MatchingService

router = APIRouter(prefix="/demands", tags=["demands"])

DemandCreator = Annotated[User, Depends(require_permissions(DEMAND_CREATE))]
DemandUpdater = Annotated[User, Depends(require_permissions(DEMAND_UPDATE_OWN))]


def _demand_out(service: DemandService, demand: object) -> BuyerDemandOut:
    """Serialise a demand with buyer and match-count enrichment."""
    return BuyerDemandOut.model_validate(service.enrich(demand))


@router.get("", response_model=Page[BuyerDemandOut], summary="Browse demands")
def list_demands(
    session: DbSession,
    params: Pagination,
    user: OptionalUser,
    status_list: list[DemandStatus] | None = Query(
        None, alias="status", description="Restrict to these demand statuses"
    ),
    commodity_id: uuid.UUID | None = Query(None, description="Filter by commodity"),
    district: str | None = Query(None, description="Delivery district"),
    min_grade: str | None = Query(None, description="Minimum quality grade"),
    required_by_before: date | None = Query(None, description="Needed on or before"),
    required_by_after: date | None = Query(None, description="Needed on or after"),
    min_quantity: float | None = Query(None, description="Minimum required quantity"),
    term: str | None = Query(None, description="Free-text search term"),
    sort: str = "-created_at",
) -> Page[BuyerDemandOut]:
    """Browse open buyer requirements with matched-lot counts attached."""
    service = DemandService(session)
    items, total = service.list_demands(
        status=status_list,
        commodity_id=commodity_id,
        district=district,
        min_grade=min_grade,
        required_by_before=required_by_before,
        required_by_after=required_by_after,
        min_quantity=min_quantity,
        term=term,
        sort=sort,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[BuyerDemandOut].build([_demand_out(service, d) for d in items], total, params)


@router.get("/mine", response_model=Page[BuyerDemandOut], summary="List own demands")
def my_demands(session: DbSession, params: Pagination, user: CurrentBuyer) -> Page[BuyerDemandOut]:
    """The caller's own purchase requirements, most recent first."""
    service = DemandService(session)
    items, total = service.list_demands(
        buyer_user_id=user.id, page=params.page, page_size=params.page_size
    )
    return Page[BuyerDemandOut].build([_demand_out(service, d) for d in items], total, params)


@router.post(
    "",
    response_model=BuyerDemandOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a demand",
)
def create_demand(
    payload: BuyerDemandCreate, session: DbSession, user: DemandCreator
) -> BuyerDemandOut:
    """Publish a purchase requirement and open it up to matching."""
    service = DemandService(session)
    demand = service.create_demand(payload, user)
    session.commit()
    return _demand_out(service, demand)


@router.get("/{demand_id}", response_model=BuyerDemandOut, summary="Demand detail")
def get_demand(demand_id: uuid.UUID, session: DbSession, user: CurrentUser) -> BuyerDemandOut:
    """Return a single demand with its active-offer and match counts."""
    service = DemandService(session)
    return _demand_out(service, service.get_demand(demand_id))


@router.patch("/{demand_id}", response_model=BuyerDemandOut, summary="Update a demand")
def update_demand(
    demand_id: uuid.UUID,
    payload: BuyerDemandUpdate,
    session: DbSession,
    user: DemandUpdater,
) -> BuyerDemandOut:
    """Edit the caller's own demand while it is still open."""
    service = DemandService(session)
    demand = service.update_demand(demand_id, payload, user)
    session.commit()
    return _demand_out(service, demand)


@router.post("/{demand_id}/close", response_model=BuyerDemandOut, summary="Close a demand")
def close_demand(
    demand_id: uuid.UUID,
    session: DbSession,
    user: CurrentBuyer,
    reason: str | None = Query(None, max_length=255),
) -> BuyerDemandOut:
    """Mark the caller's own requirement as closed; it stops matching."""
    service = DemandService(session)
    demand = service.close_demand(demand_id, user, reason=reason)
    session.commit()
    return _demand_out(service, demand)


@router.get(
    "/{demand_id}/matches",
    response_model=list[MatchResult],
    summary="Lots for a demand",
)
def demand_matches(
    demand_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
) -> list[MatchResult]:
    """Ranked lots that can fulfil this demand, best score first."""
    demand = DemandService(session).get_demand(demand_id)
    return MatchingService(session).match_demand_to_lots(
        demand, commodity=demand.commodity, limit=limit
    )


__all__ = ["router"]
