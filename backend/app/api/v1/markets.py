"""Public market intelligence endpoints: catalog, prices, trends and arrivals."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession, OptionalUser, Pagination
from app.core.enums import MarketType
from app.models import MarketPrice, QualityAttribute
from app.repositories.markets import QualityAttributeRepository
from app.schemas.common import Page
from app.schemas.market import (
    CommodityOut,
    MarketComparison,
    MarketOut,
    MarketPriceOut,
    MarketPriceTrend,
    QualityAttributeOut,
)
from app.services.market_service import MarketService

router = APIRouter(prefix="/markets", tags=["markets"])


def _price_out(price: MarketPrice) -> MarketPriceOut:
    """Serialise a price row together with its market and commodity labels.

    The row itself only stores foreign keys, but every price surface is read by
    people, so the display names travel with the numbers.
    """
    return MarketPriceOut(
        id=price.id,
        market_id=price.market_id,
        market_name=price.market.name if price.market else None,
        market_type=price.market.market_type if price.market else None,
        commodity_id=price.commodity_id,
        commodity_name=price.commodity.name if price.commodity else None,
        price_date=price.price_date,
        min_price=price.min_price,
        max_price=price.max_price,
        modal_price=price.modal_price,
        arrivals_quantity=price.arrivals_quantity,
        arrivals_unit=price.arrivals_unit,
        unit=price.unit,
        source=price.source,
        is_demo=price.is_demo,
    )


@router.get("/districts", response_model=list[str], summary="List market districts")
def districts(session: DbSession, user: OptionalUser) -> list[str]:
    """Every district that has at least one active market, for filter dropdowns."""
    return MarketService(session).districts()


@router.get("/commodities", response_model=list[CommodityOut], summary="List commodities")
def list_commodities(
    session: DbSession,
    user: OptionalUser,
    term: str | None = Query(None, description="Match name, code or category"),
) -> list[CommodityOut]:
    """The tradeable crop catalog. Only active commodities are ever returned."""
    service = MarketService(session)
    return [CommodityOut.model_validate(item) for item in service.list_commodities(term)]


@router.get("/markets", response_model=list[MarketOut], summary="List markets")
def list_markets(
    session: DbSession,
    user: OptionalUser,
    district: str | None = Query(None, description="Filter by district"),
    market_type: MarketType | None = Query(None, description="Filter by market type"),
    term: str | None = Query(None, description="Match name, code or taluka"),
    commodity_id: uuid.UUID | None = Query(None, description="Only markets quoting this commodity"),
) -> list[MarketOut]:
    """Active markets, optionally narrowed to those with a quote for a commodity."""
    service = MarketService(session)
    markets = service.list_markets(
        district=district,
        market_type=market_type,
        term=term,
        commodity_id=commodity_id,
    )
    return [MarketOut.model_validate(market) for market in markets]


@router.get("/overview", response_model=list[dict[str, Any]], summary="Cross-commodity overview")
def commodity_overview(
    session: DbSession,
    user: OptionalUser,
    limit: int = Query(12, ge=1, le=50, description="How many commodities to summarise"),
) -> list[dict[str, Any]]:
    """One row per crop: current modal range, 7-day change and market coverage.

    Commodities without any recorded price are omitted rather than shown as zero,
    so the overview never implies a rate that does not exist.
    """
    return MarketService(session).commodity_price_overview(limit=limit)


@router.get("/price-snapshot", response_model=dict[str, Any], summary="Commodity price snapshot")
def price_snapshot(
    session: DbSession,
    user: OptionalUser,
    commodity_id: uuid.UUID = Query(..., description="Commodity to summarise"),
    district: str | None = Query(None, description="Restrict to one district"),
    origin_latitude: float | None = Query(
        None, ge=-90, le=90, description="Seller latitude, for distance ranking"
    ),
    origin_longitude: float | None = Query(
        None, ge=-180, le=180, description="Seller longitude, for distance ranking"
    ),
    radius_km: float | None = Query(
        None, gt=0, le=2000, description="Keep only markets within this distance"
    ),
) -> dict[str, Any]:
    """Compact per-market price view with min/median/max and 7-day change.

    Passing coordinates adds a distance to every market and lets the caller keep
    only the reachable ones; the same payload backs the dashboards and the seeder.
    """
    return MarketService(session).price_snapshot(
        commodity_id,
        district=district,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
        radius_km=radius_km,
    )


@router.get("/arrivals", response_model=list[dict[str, Any]], summary="Arrival series")
def arrivals(
    session: DbSession,
    user: OptionalUser,
    commodity_id: uuid.UUID = Query(..., description="Commodity to report on"),
    days: int = Query(30, ge=1, le=365, description="Window length in days"),
    district: str | None = Query(None, description="Restrict to one district"),
) -> list[dict[str, Any]]:
    """Daily arrival tonnage for a crop, oldest first.

    Heavy arrivals are what softens a mandi price, so this series is meant to be
    read next to the price trend rather than on its own.
    """
    return MarketService(session).arrival_trend(commodity_id, days=days, district=district)


@router.get("/prices", response_model=Page[MarketPriceOut], summary="Search price records")
def query_prices(
    session: DbSession,
    params: Pagination,
    user: OptionalUser,
    commodity_id: uuid.UUID | None = Query(None, description="Filter by commodity"),
    market_id: uuid.UUID | None = Query(None, description="Filter by market"),
    district: str | None = Query(None, description="Filter by district"),
    market_type: MarketType | None = Query(None, description="Filter by market type"),
    from_date: date | None = Query(None, description="Earliest price date"),
    to_date: date | None = Query(None, description="Latest price date"),
    min_price: float | None = Query(None, ge=0, description="Minimum modal price"),
    max_price: float | None = Query(None, ge=0, description="Maximum modal price"),
    sort: str = Query("-price_date", description="Sort field, prefix with - to reverse"),
) -> Page[MarketPriceOut]:
    """Filter the recorded price rows.

    Dates default to today when omitted, so an unfiltered call is a single-day
    board rather than the whole history.
    """
    service = MarketService(session)
    rows, total = service.query_prices(
        commodity_id=commodity_id,
        market_id=market_id,
        district=district,
        market_type=market_type,
        from_date=from_date,
        to_date=to_date,
        min_price=min_price,
        max_price=max_price,
        page=params.page,
        page_size=params.page_size,
        sort=sort,
    )
    return Page[MarketPriceOut].build([_price_out(row) for row in rows], total, params)


@router.get("/prices/latest", response_model=list[MarketPriceOut], summary="Latest price board")
def latest_prices(
    session: DbSession,
    user: OptionalUser,
    commodity_id: uuid.UUID | None = Query(None, description="Filter by commodity"),
    district: str | None = Query(None, description="Filter by district"),
) -> list[MarketPriceOut]:
    """One most-recent row per market and commodity, the usual landing-page board."""
    service = MarketService(session)
    return [
        _price_out(price)
        for price in service.latest_price_board(commodity_id=commodity_id, district=district)
    ]


@router.get(
    "/prices/trend",
    response_model=MarketPriceTrend,
    summary="Price trend for a commodity",
)
def price_trend(
    session: DbSession,
    user: OptionalUser,
    commodity_id: uuid.UUID = Query(..., description="Commodity to chart"),
    days: int = Query(30, ge=1, le=365, description="Window length in days"),
    district: str | None = Query(None, description="Restrict to one district"),
    market_id: uuid.UUID | None = Query(None, description="Restrict to one market"),
) -> MarketPriceTrend:
    """Daily modal/min/max averaged across the selected markets, plus the change.

    ``is_demo_data`` is set when any point came from seeded rather than provider
    data; the client is expected to surface the disclaimer whenever it is true.
    """
    return MarketService(session).trend(
        commodity_id, days=days, district=district, market_id=market_id
    )


@router.get(
    "/prices/comparison",
    response_model=MarketComparison,
    summary="Compare markets on a date",
)
def price_comparison(
    session: DbSession,
    user: OptionalUser,
    commodity_id: uuid.UUID = Query(..., description="Commodity to compare"),
    on_date: date | None = Query(None, description="Compare prices as at this date"),
    district: str | None = Query(None, description="Restrict to one district"),
    origin_latitude: float | None = Query(
        None, ge=-90, le=90, description="Origin latitude, for distance ranking"
    ),
    origin_longitude: float | None = Query(
        None, ge=-180, le=180, description="Origin longitude, for distance ranking"
    ),
) -> MarketComparison:
    """Rank markets for one crop on a given day and name the best and nearest.

    "Best" is the highest modal price and "nearest" only exists when the caller
    supplied coordinates, so a seller trades off rate against transport.
    """
    return MarketService(session).market_comparison(
        commodity_id,
        on_date=on_date,
        district=district,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
    )


@router.get(
    "/commodities/{commodity_id}",
    response_model=CommodityOut,
    summary="Commodity detail",
)
def get_commodity(commodity_id: uuid.UUID, session: DbSession, user: OptionalUser) -> CommodityOut:
    """A single commodity from the catalog, including units and seasonality notes."""
    return CommodityOut.model_validate(MarketService(session).get_commodity(commodity_id))


@router.get(
    "/commodities/{commodity_id}/attributes",
    response_model=list[QualityAttributeOut],
    summary="Grading attributes for a commodity",
)
def commodity_attributes(
    commodity_id: uuid.UUID, session: DbSession, user: OptionalUser
) -> list[QualityAttributeOut]:
    """Published quality bands (moisture, size, damage...) used to grade a lot."""
    attributes = QualityAttributeRepository(QualityAttribute, session).for_commodity(commodity_id)
    return [QualityAttributeOut.model_validate(attribute) for attribute in attributes]


@router.get("/markets/{market_id}", response_model=dict[str, Any], summary="Market detail")
def market_detail(
    market_id: uuid.UUID,
    session: DbSession,
    user: OptionalUser,
    days: int = Query(30, ge=1, le=365, description="History window echoed back to the client"),
) -> dict[str, Any]:
    """A market with its latest quoted price for every active commodity."""
    service = MarketService(session)
    market = service.get_market(market_id)
    detail = service.market_detail(market_id, days=days)
    return {
        "market": MarketOut.model_validate(market),
        "latest_prices": [_price_out(price) for price in detail["latest_prices"]],
        "days": detail["days"],
    }


__all__ = ["router"]
