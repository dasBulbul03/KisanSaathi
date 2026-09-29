"""Market intelligence service: prices, trends, comparisons, arrivals."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models import (
    Commodity,
    Market,
    MarketArrival,
    MarketDataSyncLog,
    MarketPrice,
    QualityAttribute,
)
from app.repositories.markets import (
    CommodityRepository,
    MarketArrivalRepository,
    MarketPriceRepository,
    MarketRepository,
    QualityAttributeRepository,
    prices_with_filters,
)
from app.schemas.market import (
    PRICE_DISCLAIMER,
    MarketComparison,
    MarketComparisonRow,
    MarketPriceTrend,
    MarketPriceTrendPoint,
)
from app.utils.geo import haversine_km

logger = get_logger(__name__)


class MarketService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.commodities = CommodityRepository(Commodity, session)
        self.markets = MarketRepository(Market, session)
        self.prices = MarketPriceRepository(MarketPrice, session)
        self.arrivals = MarketArrivalRepository(MarketArrival, session)
        self.quality_attributes = QualityAttributeRepository(QualityAttribute, session)

    # ------------------------------------------------------------- lookups
    def get_commodity(self, commodity_id: uuid.UUID) -> Commodity:
        commodity = self.commodities.get(commodity_id)
        if commodity is None or not commodity.is_active:
            raise NotFoundError("Commodity not found.", code="COMMODITY_NOT_FOUND")
        return commodity

    def get_market(self, market_id: uuid.UUID) -> Market:
        market = self.markets.get(market_id)
        if market is None:
            raise NotFoundError("Market not found.", code="MARKET_NOT_FOUND")
        return market

    def list_commodities(self, term: str | None = None) -> list[Commodity]:
        if term:
            return list(self.session.execute(self.commodities.search(term)).scalars().all())
        return self.commodities.active()

    def list_markets(
        self,
        *,
        district: str | None = None,
        market_type: str | None = None,
        term: str | None = None,
        commodity_id: uuid.UUID | None = None,
    ) -> list[Market]:
        stmt = self.markets.filter_query(
            district=district,
            market_type=market_type,
            term=term,
            commodity_id=commodity_id,
        )
        return list(self.session.execute(stmt).scalars().all())

    def districts(self) -> list[str]:
        return self.markets.districts()

    def market_detail(self, market_id: uuid.UUID, *, days: int = 30) -> dict[str, Any]:
        market = self.get_market(market_id)
        latest: list[MarketPrice] = []
        for commodity in self.commodities.active():
            price = self.prices.latest_for_market(market_id, commodity.id)
            if price is not None:
                latest.append(price)
        latest.sort(key=lambda p: (p.commodity.name if p.commodity else ""))
        return {
            "market": market,
            "latest_prices": latest,
            "days": days,
        }

    # -------------------------------------------------------------- prices
    def query_prices(
        self,
        *,
        commodity_id: uuid.UUID | None = None,
        market_id: uuid.UUID | None = None,
        district: str | None = None,
        market_type: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        page: int = 1,
        page_size: int = 25,
        sort: str = "-price_date",
    ) -> tuple[list[MarketPrice], int]:
        stmt = prices_with_filters(
            self.prices,
            commodity_id=commodity_id,
            market_id=market_id,
            district=district,
            market_type=market_type,
            from_date=from_date,
            to_date=to_date,
            min_price=min_price,
            max_price=max_price,
        )
        for token in [sort, "modal_price"]:
            descending = token.startswith("-")
            field = token.lstrip("-")
            column = getattr(MarketPrice, field, None)
            if column is not None:
                stmt = stmt.order_by(column.desc() if descending else column.asc())
        return self.prices.paginate(stmt=stmt, page=page, page_size=page_size)

    def latest_price_board(
        self, *, commodity_id: uuid.UUID | None = None, district: str | None = None
    ) -> list[MarketPrice]:
        today = date.today()
        stmt = self.prices._with_refs().join(Market).where(MarketPrice.price_date <= today)
        if commodity_id:
            stmt = stmt.where(MarketPrice.commodity_id == commodity_id)
        if district:
            stmt = stmt.where(Market.district == district)
        rows = list(
            self.session.execute(stmt.order_by(MarketPrice.price_date.desc()))
            .unique()
            .scalars()
            .all()
        )
        seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
        board: list[MarketPrice] = []
        for row in rows:
            key = (row.market_id, row.commodity_id)
            if key in seen:
                continue
            seen.add(key)
            board.append(row)
        return board

    # -------------------------------------------------------------- trends
    def trend(
        self,
        commodity_id: uuid.UUID,
        *,
        days: int = 30,
        district: str | None = None,
        market_id: uuid.UUID | None = None,
    ) -> MarketPriceTrend:
        commodity = self.get_commodity(commodity_id)
        to_date = date.today()
        from_date = to_date - timedelta(days=max(1, days) - 1)
        market_ids = [market_id] if market_id else None
        rows = self.prices.prices_for_commodity(
            commodity_id,
            from_date=from_date,
            to_date=to_date,
            district=district,
            market_ids=market_ids,
        )
        by_date: dict[date, list[MarketPrice]] = {}
        for row in rows:
            by_date.setdefault(row.price_date, []).append(row)
        points = [
            MarketPriceTrendPoint(
                date=day,
                modal_price=round(sum(p.modal_price for p in group) / len(group), 2),
                min_price=min(p.min_price for p in group),
                max_price=max(p.max_price for p in group),
                arrivals_quantity=round(sum(p.arrivals_quantity or 0 for p in group), 2) or None,
                market_count=len({p.market_id for p in group}),
            )
            for day, group in sorted(by_date.items())
        ]
        overall_change = None
        if len(points) >= 2 and points[0].modal_price:
            overall_change = round(
                (points[-1].modal_price - points[0].modal_price) / points[0].modal_price * 100, 2
            )
        return MarketPriceTrend(
            commodity_id=commodity_id,
            commodity_name=commodity.name,
            unit=commodity.default_unit,
            from_date=from_date,
            to_date=to_date,
            points=points,
            district_median_modal_price=round(median(p.modal_price for p in points), 2)
            if points
            else None,
            overall_change_pct=overall_change,
            is_demo_data=any(p.is_demo for p in rows),
            disclaimer=PRICE_DISCLAIMER,
        )

    def market_comparison(
        self,
        commodity_id: uuid.UUID,
        *,
        on_date: date | None = None,
        district: str | None = None,
        origin_latitude: float | None = None,
        origin_longitude: float | None = None,
    ) -> MarketComparison:
        commodity = self.get_commodity(commodity_id)
        target = on_date or date.today()
        latest = self.prices.latest_by_commodity(commodity_id, target)
        if district:
            latest = [p for p in latest if p.market and p.market.district == district]
        rows: list[MarketComparisonRow] = []
        for price in latest:
            if price.market is None:
                continue
            distance = None
            if origin_latitude is not None and price.market.latitude is not None:
                distance = haversine_km(
                    origin_latitude,
                    origin_longitude or 0.0,
                    price.market.latitude,
                    price.market.longitude or 0.0,
                )
            rows.append(
                MarketComparisonRow(
                    market_id=price.market_id,
                    market_name=price.market.name,
                    district=price.market.district,
                    modal_price=price.modal_price,
                    min_price=price.min_price,
                    max_price=price.max_price,
                    arrivals_quantity=price.arrivals_quantity,
                    distance_km=distance,
                    change_pct_7d=self.prices.change_pct(price.market_id, commodity_id, 7),
                )
            )
        rows.sort(key=lambda r: r.modal_price, reverse=True)
        best = rows[0] if rows else None
        nearest = None
        if rows:
            with_distance = [r for r in rows if r.distance_km is not None]
            nearest = (
                min(with_distance, key=lambda r: r.distance_km or 0) if with_distance else None
            )
        return MarketComparison(
            commodity_id=commodity_id,
            commodity_name=commodity.name,
            price_date=target,
            rows=rows,
            best_market_id=best.market_id if best else None,
            nearest_market_id=nearest.market_id if nearest else None,
            is_demo_data=any(
                p.is_demo
                for p in self.prices.prices_for_commodity(
                    commodity_id,
                    from_date=target - timedelta(days=3),
                    to_date=target,
                )
            ),
            disclaimer=PRICE_DISCLAIMER,
        )

    def arrival_trend(
        self, commodity_id: uuid.UUID, *, days: int = 30, district: str | None = None
    ) -> list[dict[str, Any]]:
        to_date = date.today()
        from_date = to_date - timedelta(days=max(1, days) - 1)
        series = self.arrivals.series(
            commodity_id, from_date=from_date, to_date=to_date, district=district
        )
        return [{"date": d.isoformat(), "quantity": q} for d, q in series]

    def arrivals_for_commodity(
        self, commodity_id: uuid.UUID, *, days: int = 3, district: str | None = None
    ) -> dict[str, float]:
        return {
            "recent": self.arrivals.recent_total(commodity_id, days=days, district=district),
            "previous": self.arrivals.previous_total(commodity_id, days=days, district=district),
        }

    # ------------------------------------------------------- price summary
    def price_snapshot(
        self,
        commodity_id: uuid.UUID,
        *,
        district: str | None = None,
        origin_latitude: float | None = None,
        origin_longitude: float | None = None,
        radius_km: float | None = None,
    ) -> dict[str, Any]:
        """Compact price view used by dashboards, the AI tools and the seeder."""
        commodity = self.get_commodity(commodity_id)
        latest = self.prices.latest_by_commodity(commodity_id, date.today())
        entries: list[dict[str, Any]] = []
        for price in latest:
            if price.market is None:
                continue
            distance = None
            if origin_latitude is not None and price.market.latitude is not None:
                distance = haversine_km(
                    origin_latitude,
                    origin_longitude or 0.0,
                    price.market.latitude,
                    price.market.longitude or 0.0,
                )
            entries.append(
                {
                    "market_id": str(price.market_id),
                    "market_name": price.market.name,
                    "district": price.market.district,
                    "market_type": price.market.market_type.value,
                    "date": price.price_date.isoformat(),
                    "min_price": price.min_price,
                    "max_price": price.max_price,
                    "modal_price": price.modal_price,
                    "arrivals_quantity": price.arrivals_quantity,
                    "unit": price.unit,
                    "distance_km": distance,
                    "is_demo": price.is_demo,
                    "change_pct_7d": self.prices.change_pct(price.market_id, commodity_id, 7),
                }
            )
        if district:
            entries = [e for e in entries if e["district"] == district]
        if radius_km is not None:
            entries = [
                e for e in entries if e["distance_km"] is None or e["distance_km"] <= radius_km
            ]
        modals = [e["modal_price"] for e in entries]
        return {
            "commodity_id": str(commodity_id),
            "commodity_name": commodity.name,
            "unit": commodity.default_unit,
            "as_of": date.today().isoformat(),
            "markets": entries,
            "market_count": len(entries),
            "min_modal": min(modals) if modals else None,
            "max_modal": max(modals) if modals else None,
            "median_modal": round(median(modals), 2) if modals else None,
            "district_median": round(median(modals), 2) if modals and district else None,
            "is_demo_data": any(e["is_demo"] for e in entries),
            "disclaimer": PRICE_DISCLAIMER,
        }

    def trend_series(
        self,
        commodity_id: uuid.UUID,
        *,
        days: int = 7,
        district: str | None = None,
        market_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        trend = self.trend(commodity_id, days=days, district=district, market_id=market_id)
        return {
            "commodity_id": str(commodity_id),
            "commodity_name": trend.commodity_name,
            "unit": trend.unit,
            "labels": [p.date.isoformat() for p in trend.points],
            "values": [p.modal_price for p in trend.points],
            "min_values": [p.min_price for p in trend.points],
            "max_values": [p.max_price for p in trend.points],
            "arrivals": [p.arrivals_quantity for p in trend.points],
            "overall_change_pct": trend.overall_change_pct,
            "is_demo_data": trend.is_demo_data,
            "disclaimer": PRICE_DISCLAIMER,
        }

    # ------------------------------------------------------- admin helpers
    def create_sync_log(
        self,
        *,
        provider: str,
        started_at: datetime,
        status: str,
        records_processed: int = 0,
        records_inserted: int = 0,
        records_updated: int = 0,
        message: str | None = None,
    ) -> MarketDataSyncLog:
        log = MarketDataSyncLog(
            provider=provider,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(),
            records_processed=records_processed,
            records_inserted=records_inserted,
            records_updated=records_updated,
            message=message,
        )
        # Flushed rather than just added: callers return the id straight away, and
        # a log that only lands at commit time would hand back None.
        self.session.add(log)
        self.session.flush()
        return log

    def recent_sync_logs(self, limit: int = 20) -> list[MarketDataSyncLog]:
        from app.repositories.base import BaseRepository

        repo = BaseRepository(MarketDataSyncLog, self.session)
        return repo.find_all(order_by=["-started_at"], limit=limit)

    def commodity_price_overview(self, *, limit: int = 12) -> list[dict[str, Any]]:
        """Cross-commodity view used by the landing page and admin analytics."""
        out: list[dict[str, Any]] = []
        for commodity in self.commodities.active()[:limit]:
            snapshot = self.price_snapshot(commodity.id)
            if snapshot["median_modal"] is None:
                continue
            trend = self.trend(commodity.id, days=7)
            out.append(
                {
                    "commodity_id": str(commodity.id),
                    "commodity": commodity.name,
                    "category": commodity.category,
                    "unit": commodity.default_unit,
                    "median_modal_price": snapshot["median_modal"],
                    "min_modal": snapshot["min_modal"],
                    "max_modal": snapshot["max_modal"],
                    "change_pct_7d": trend.overall_change_pct,
                    "market_count": snapshot["market_count"],
                    "is_demo_data": snapshot["is_demo_data"],
                }
            )
        return out


def price_direction(change_pct: float | None) -> str:
    if change_pct is None:
        return "STABLE"
    if change_pct > 1.5:
        return "RISING"
    if change_pct < -1.5:
        return "FALLING"
    return "STABLE"
