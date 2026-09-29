"""Platform administration endpoints: health, market data, audit and catalogue."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentAdmin,
    DbSession,
    Pagination,
    require_permissions,
    require_roles,
)
from app.core.config import settings
from app.core.enums import MarketType, UserRole
from app.core.exceptions import NotFoundError
from app.core.rbac import (
    AUDIT_READ,
    COMMODITY_MANAGE,
    MARKET_MANAGE,
    PRICE_MANAGE,
)
from app.db.session import check_database
from app.models import AuditLog, Commodity, Market, User
from app.repositories.markets import CommodityRepository, MarketRepository
from app.repositories.operations import AuditRepository
from app.schemas.common import Page
from app.schemas.market import (
    CommodityCreate,
    CommodityOut,
    CommodityUpdate,
    MarketCreate,
    MarketDataSyncLogOut,
    MarketOut,
    MarketUpdate,
)
from app.schemas.operations import AuditLogOut
from app.services.market_service import MarketService
from app.services.market_sync_service import MarketDataSyncService

# ``CurrentAdmin`` is an ``Annotated`` alias and FastAPI cannot resolve one inside
# ``Depends(...)`` at router level - it would register phantom query parameters -
# so the blanket guard names the underlying role dependency.
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)

PriceMaintainer = Annotated[User, Depends(require_permissions(PRICE_MANAGE))]
AuditReader = Annotated[User, Depends(require_permissions(AUDIT_READ))]
CatalogManager = Annotated[User, Depends(require_permissions(COMMODITY_MANAGE))]
MarketMaintainer = Annotated[User, Depends(require_permissions(MARKET_MANAGE))]


class SyncRequest(BaseModel):
    """Which market data to pull, and for how far back."""

    days: int = Field(default=3, ge=1, le=365, description="Recent days to refresh")
    history_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Wider backfill window; 30 days when omitted",
    )
    commodity_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Restrict to these commodities; all active ones by default",
    )
    market_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Restrict to these markets; all active ones by default",
    )
    include_arrivals: bool = Field(default=True, description="Also refresh inward arrival volumes")


def _create_commodity(session: Session, payload: CommodityCreate) -> Commodity:
    """Insert a commodity straight from the validated payload."""
    commodity = CommodityRepository(Commodity, session).create(**payload.model_dump())
    session.commit()
    return commodity


def _update_commodity(
    session: Session, commodity_id: uuid.UUID, payload: CommodityUpdate
) -> Commodity:
    """Apply only the supplied fields; anything omitted keeps its stored value."""
    repo = CommodityRepository(Commodity, session)
    commodity = repo.get(commodity_id)
    if commodity is None:
        raise NotFoundError("Commodity not found.", code="COMMODITY_NOT_FOUND")
    repo.update(commodity, **payload.model_dump(exclude_unset=True))
    session.commit()
    return commodity


def _create_market(session: Session, payload: MarketCreate) -> Market:
    """Insert a market straight from the validated payload."""
    market = MarketRepository(Market, session).create(**payload.model_dump())
    session.commit()
    return market


def _update_market(session: Session, market_id: uuid.UUID, payload: MarketUpdate) -> Market:
    """Apply only the supplied fields; anything omitted keeps its stored value."""
    repo = MarketRepository(Market, session)
    market = repo.get(market_id)
    if market is None:
        raise NotFoundError("Market not found.", code="MARKET_NOT_FOUND")
    repo.update(market, **payload.model_dump(exclude_unset=True))
    session.commit()
    return market


@router.get("/health", response_model=dict[str, Any], summary="Platform health")
def health(session: DbSession, user: CurrentAdmin) -> dict[str, Any]:
    """Liveness of the database and the market data feed in one call.

    ``market_data.ready`` stays false until a reachable provider and configured
    commodities and markets all exist, which is what a sync needs to do work.
    """
    return {
        "database": check_database(),
        "market_data": MarketDataSyncService(session).health(),
        "environment": settings.ENVIRONMENT,
        "version": settings.APP_VERSION,
    }


@router.post(
    "/market-data/sync",
    response_model=dict[str, Any],
    summary="Run a market data sync",
)
def sync_market_data(
    payload: SyncRequest, session: DbSession, user: PriceMaintainer
) -> dict[str, Any]:
    """Pull prices, and optionally arrivals, from the configured provider.

    Idempotent: rows are keyed on market, commodity and date, so a repeat run
    refreshes in place instead of duplicating. Every run - successful or not -
    appends a market data sync log, so a broken feed shows up here.
    """
    return MarketDataSyncService(session).sync(triggered_by_user_id=user.id, **payload.model_dump())


@router.get(
    "/market-data/sync-logs",
    response_model=list[MarketDataSyncLogOut],
    summary="Recent sync runs",
)
def sync_logs(
    session: DbSession,
    user: PriceMaintainer,
    limit: int = Query(20, ge=1, le=100, description="Newest runs to return"),
) -> list[MarketDataSyncLogOut]:
    """The last few provider runs with their row counts and failure messages."""
    return [
        MarketDataSyncLogOut.model_validate(log)
        for log in MarketService(session).recent_sync_logs(limit)
    ]


@router.get(
    "/audit-logs",
    response_model=Page[AuditLogOut],
    summary="Search the audit trail",
)
def list_audit_logs(
    session: DbSession,
    params: Pagination,
    user: AuditReader,
    actor_user_id: uuid.UUID | None = Query(None, description="Filter by actor"),
    action: str | None = Query(None, description="Exact action name, e.g. LOGIN"),
    entity_type: str | None = Query(None, description="Entity type, e.g. user or order"),
    entity_id: str | None = Query(None, description="Entity id within that type"),
    request_id: str | None = Query(None, description="Correlate with a request id"),
    from_date: datetime | None = Query(None, description="Only entries at or after"),
) -> Page[AuditLogOut]:
    """Search the append-only audit trail, newest first.

    Filters combine, so one call can pull everything one actor did to one
    entity inside a time window.
    """
    repo = AuditRepository(AuditLog, session)
    rows, total = repo.paginate(
        stmt=repo.search(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=request_id,
            from_date=from_date,
        ),
        page=params.page,
        page_size=params.page_size,
    )
    return Page[AuditLogOut].build([AuditLogOut.model_validate(row) for row in rows], total, params)


@router.get(
    "/audit-logs/{entity_type}/{entity_id}",
    response_model=list[AuditLogOut],
    summary="History for one entity",
)
def entity_audit_history(
    entity_type: str,
    entity_id: str,
    session: DbSession,
    user: AuditReader,
) -> list[AuditLogOut]:
    """Every recorded change to a single entity, newest first.

    This is the drill-down behind a suspicious order or a disputed grade.
    """
    return [
        AuditLogOut.model_validate(log)
        for log in AuditRepository(AuditLog, session).entity_history(entity_type, entity_id)
    ]


@router.get(
    "/commodities",
    response_model=Page[CommodityOut],
    summary="List catalogue commodities",
)
def list_commodities(
    session: DbSession,
    params: Pagination,
    user: CatalogManager,
    term: str | None = Query(None, description="Match name, code or category"),
    include_inactive: bool = Query(
        False, description="Include commodities retired from the marketplace"
    ),
) -> Page[CommodityOut]:
    """Commodities in the catalogue, including retired ones by request.

    Retired rows are included by default here rather than hidden, otherwise a
    commodity retired with ``is_active=false`` would disappear from the very
    screen used to bring it back.
    """
    repo = CommodityRepository(Commodity, session)
    rows, total = repo.paginate(
        stmt=repo.search(term, include_inactive=include_inactive),
        page=params.page,
        page_size=params.page_size,
    )
    return Page[CommodityOut].build(
        [CommodityOut.model_validate(row) for row in rows], total, params
    )


@router.post(
    "/commodities",
    response_model=CommodityOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a commodity",
)
def create_commodity(
    payload: CommodityCreate, session: DbSession, user: CatalogManager
) -> CommodityOut:
    """Add a commodity to the catalogue; its code must be unique.

    It becomes selectable in lot creation and matching as soon as it exists.
    """
    return CommodityOut.model_validate(_create_commodity(session, payload))


@router.patch(
    "/commodities/{commodity_id}",
    response_model=CommodityOut,
    summary="Edit a commodity",
)
def update_commodity(
    commodity_id: uuid.UUID,
    payload: CommodityUpdate,
    session: DbSession,
    user: CatalogManager,
) -> CommodityOut:
    """Edit catalogue details, or retire a commodity with ``is_active=false``."""
    return CommodityOut.model_validate(_update_commodity(session, commodity_id, payload))


@router.get("/markets", response_model=Page[MarketOut], summary="List markets")
def list_markets(
    session: DbSession,
    params: Pagination,
    user: MarketMaintainer,
    term: str | None = Query(None, description="Match name, code or taluka"),
    district: str | None = Query(None, description="Exact district match"),
    market_type: MarketType | None = Query(None, description="Mandi, farm gate, ..."),
    include_inactive: bool = Query(False, description="Include retired markets"),
) -> Page[MarketOut]:
    """Markets, retired ones included by request, grouped by district then name."""
    repo = MarketRepository(Market, session)
    rows, total = repo.paginate(
        stmt=repo.filter_query(
            term=term,
            district=district,
            market_type=market_type,
            include_inactive=include_inactive,
        ),
        page=params.page,
        page_size=params.page_size,
    )
    return Page[MarketOut].build([MarketOut.model_validate(row) for row in rows], total, params)


@router.post(
    "/markets",
    response_model=MarketOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a market",
)
def create_market(payload: MarketCreate, session: DbSession, user: MarketMaintainer) -> MarketOut:
    """Add a market; its code is the key the price provider quotes against."""
    return MarketOut.model_validate(_create_market(session, payload))


@router.patch(
    "/markets/{market_id}",
    response_model=MarketOut,
    summary="Edit a market",
)
def update_market(
    market_id: uuid.UUID,
    payload: MarketUpdate,
    session: DbSession,
    user: MarketMaintainer,
) -> MarketOut:
    """Edit market details, or take a market out of rotation with ``is_active=false``."""
    return MarketOut.model_validate(_update_market(session, market_id, payload))


__all__ = ["router"]
