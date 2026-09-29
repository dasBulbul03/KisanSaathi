"""Catalog, market price and arrival repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import joinedload

from app.models import (
    Commodity,
    Market,
    MarketArrival,
    MarketPrice,
    QualityAttribute,
)
from app.repositories.base import BaseRepository


class CommodityRepository(BaseRepository[Commodity]):
    def active(self) -> list[Commodity]:
        return self.find_all(filters={"is_active": True}, order_by=["name"])

    def search(self, term: str | None, *, include_inactive: bool = False) -> Select:
        """Commodity search. Admin views opt into retired rows so a de-activated
        commodity does not silently disappear from the management list."""
        stmt = self._base_query()
        if not include_inactive:
            stmt = stmt.where(Commodity.is_active.is_(True))
        if term:
            pattern = f"%{term.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Commodity.name).like(pattern),
                    func.lower(Commodity.code).like(pattern),
                    func.lower(Commodity.category).like(pattern),
                )
            )
        return stmt.order_by(Commodity.category, Commodity.name)


class MarketRepository(BaseRepository[Market]):
    def active(self) -> list[Market]:
        return self.find_all(filters={"is_active": True}, order_by=["district", "name"])

    def filter_query(
        self,
        *,
        district: str | None = None,
        market_type: str | None = None,
        term: str | None = None,
        commodity_id: uuid.UUID | None = None,
        include_inactive: bool = False,
    ) -> Select:
        stmt = self._base_query()
        if not include_inactive:
            stmt = stmt.where(Market.is_active.is_(True))
        if district:
            stmt = stmt.where(Market.district == district)
        if market_type:
            stmt = stmt.where(Market.market_type == market_type)
        if term:
            pattern = f"%{term.strip().lower()}%"
            stmt = stmt.where(
                func.lower(Market.name).like(pattern)
                | func.lower(Market.code).like(pattern)
                | func.lower(Market.taluka).like(pattern)
            )
        if commodity_id:
            stmt = stmt.where(
                Market.id.in_(
                    select(MarketPrice.market_id)
                    .where(
                        MarketPrice.commodity_id == commodity_id,
                        MarketPrice.price_date >= date.today(),
                    )
                    .distinct()
                )
            )
        return stmt.order_by(Market.district, Market.name)

    def districts(self) -> list[str]:
        stmt = (
            select(Market.district)
            .where(Market.is_active.is_(True))
            .distinct()
            .order_by(Market.district)
        )
        return list(self.session.execute(stmt).scalars().all())


class QualityAttributeRepository(BaseRepository[QualityAttribute]):
    def for_commodity(self, commodity_id: uuid.UUID) -> list[QualityAttribute]:
        return self.find_all(
            filters={"commodity_id": commodity_id, "is_active": True},
            order_by=["sort_order", "label"],
        )

    def bulk_map(
        self, commodity_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[QualityAttribute]]:
        if not commodity_ids:
            return {}
        stmt = self._base_query().where(
            QualityAttribute.commodity_id.in_(list(commodity_ids)),
            QualityAttribute.is_active.is_(True),
        )
        result: dict[uuid.UUID, list[QualityAttribute]] = {}
        for attribute in self.session.execute(stmt).scalars().all():
            result.setdefault(attribute.commodity_id, []).append(attribute)
        return result


class MarketPriceRepository(BaseRepository[MarketPrice]):
    def _with_refs(self) -> Select:
        return self._base_query().options(
            joinedload(MarketPrice.market), joinedload(MarketPrice.commodity)
        )

    def latest_for_market(
        self, market_id: uuid.UUID, commodity_id: uuid.UUID
    ) -> MarketPrice | None:
        stmt = (
            self._with_refs()
            .where(
                MarketPrice.market_id == market_id,
                MarketPrice.commodity_id == commodity_id,
            )
            .order_by(MarketPrice.price_date.desc())
            .limit(1)
        )
        return self.session.execute(stmt).unique().scalar_one_or_none()

    def latest_by_commodity(
        self, commodity_id: uuid.UUID, on_date: date | None = None
    ) -> list[MarketPrice]:
        target = on_date or date.today()
        stmt = (
            self._with_refs()
            .where(MarketPrice.commodity_id == commodity_id, MarketPrice.price_date <= target)
            .order_by(MarketPrice.price_date.desc())
        )
        rows = list(self.session.execute(stmt).unique().scalars().all())
        seen: set[uuid.UUID] = set()
        latest: list[MarketPrice] = []
        for row in rows:
            if row.market_id in seen:
                continue
            seen.add(row.market_id)
            latest.append(row)
        return latest

    def prices_for_commodity(
        self,
        commodity_id: uuid.UUID,
        *,
        from_date: date,
        to_date: date,
        district: str | None = None,
        market_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[MarketPrice]:
        stmt = (
            self._with_refs()
            .join(Market)
            .where(
                MarketPrice.commodity_id == commodity_id,
                MarketPrice.price_date >= from_date,
                MarketPrice.price_date <= to_date,
            )
        )
        if district:
            stmt = stmt.where(Market.district == district)
        if market_ids:
            stmt = stmt.where(MarketPrice.market_id.in_(list(market_ids)))
        stmt = stmt.order_by(MarketPrice.price_date.asc())
        return list(self.session.execute(stmt).unique().scalars().all())

    def price_series(
        self,
        commodity_id: uuid.UUID,
        *,
        from_date: date,
        to_date: date,
        district: str | None = None,
        market_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[tuple[date, float, float, float, float | None, int]]:
        """Returns (date, modal, min, max, arrivals, market_count) per day."""
        stmt = (
            select(
                MarketPrice.price_date,
                func.avg(MarketPrice.modal_price),
                func.min(MarketPrice.min_price),
                func.max(MarketPrice.max_price),
                func.sum(func.coalesce(MarketPrice.arrivals_quantity, 0.0)),
                func.count(func.distinct(MarketPrice.market_id)),
            )
            .join(Market, Market.id == MarketPrice.market_id)
            .where(
                MarketPrice.commodity_id == commodity_id,
                MarketPrice.price_date >= from_date,
                MarketPrice.price_date <= to_date,
            )
            .group_by(MarketPrice.price_date)
            .order_by(MarketPrice.price_date.asc())
        )
        if district:
            stmt = stmt.where(Market.district == district)
        if market_ids:
            stmt = stmt.where(MarketPrice.market_id.in_(list(market_ids)))
        rows = self.session.execute(stmt).all()
        return [
            (
                row[0],
                round(float(row[1]), 2),
                round(float(row[2]), 2),
                round(float(row[3]), 2),
                round(float(row[4]), 2) if row[4] is not None else None,
                int(row[5]),
            )
            for row in rows
        ]

    def change_pct(
        self, market_id: uuid.UUID, commodity_id: uuid.UUID, days: int = 7
    ) -> float | None:
        from datetime import timedelta

        today = date.today()
        stmt = (
            select(MarketPrice.price_date, MarketPrice.modal_price)
            .where(
                MarketPrice.market_id == market_id,
                MarketPrice.commodity_id == commodity_id,
                MarketPrice.price_date <= today,
            )
            .order_by(MarketPrice.price_date.desc())
            .limit(days + 1)
        )
        rows = list(self.session.execute(stmt).all())
        if len(rows) < 2:
            return None
        cutoff = today - timedelta(days=days)
        latest = next((r[1] for r in rows if r[0] == rows[0][0]), None)
        old = next((r[1] for r in rows if r[0] <= cutoff), None)
        if latest is None or old in (None, 0):
            return None
        return round((latest - old) / old * 100, 2)

    def exists_for(self, market_id: uuid.UUID, commodity_id: uuid.UUID, price_date: date) -> bool:
        return self.exists(market_id=market_id, commodity_id=commodity_id, price_date=price_date)


class MarketArrivalRepository(BaseRepository[MarketArrival]):
    def series(
        self,
        commodity_id: uuid.UUID,
        *,
        from_date: date,
        to_date: date,
        district: str | None = None,
    ) -> list[tuple[date, float]]:
        stmt = (
            select(MarketArrival.arrival_date, func.sum(MarketArrival.quantity))
            .join(Market, Market.id == MarketArrival.market_id)
            .where(
                MarketArrival.commodity_id == commodity_id,
                MarketArrival.arrival_date >= from_date,
                MarketArrival.arrival_date <= to_date,
            )
            .group_by(MarketArrival.arrival_date)
            .order_by(MarketArrival.arrival_date.asc())
        )
        if district:
            stmt = stmt.where(Market.district == district)
        return [(row[0], round(float(row[1]), 2)) for row in self.session.execute(stmt).all()]

    def recent_total(
        self, commodity_id: uuid.UUID, *, days: int = 3, district: str | None = None
    ) -> float:
        from datetime import timedelta

        since = date.today() - timedelta(days=days)
        stmt = select(func.coalesce(func.sum(MarketArrival.quantity), 0.0)).where(
            MarketArrival.commodity_id == commodity_id,
            MarketArrival.arrival_date >= since,
        )
        if district:
            stmt = stmt.join(Market, Market.id == MarketArrival.market_id).where(
                Market.district == district
            )
        return round(float(self.session.execute(stmt).scalar_one() or 0.0), 2)

    def previous_total(
        self, commodity_id: uuid.UUID, *, days: int = 3, district: str | None = None
    ) -> float:
        from datetime import timedelta

        today = date.today()
        stmt = select(func.coalesce(func.sum(MarketArrival.quantity), 0.0)).where(
            MarketArrival.commodity_id == commodity_id,
            MarketArrival.arrival_date >= today - timedelta(days=days * 2),
            MarketArrival.arrival_date < today - timedelta(days=days),
        )
        if district:
            stmt = stmt.join(Market, Market.id == MarketArrival.market_id).where(
                Market.district == district
            )
        return round(float(self.session.execute(stmt).scalar_one() or 0.0), 2)


def prices_with_filters(
    repo: MarketPriceRepository,
    *,
    commodity_id: uuid.UUID | None = None,
    market_id: uuid.UUID | None = None,
    district: str | None = None,
    market_type: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
) -> Select:
    stmt = (
        repo._with_refs().join(Market).where(MarketPrice.price_date >= (from_date or date.today()))
    )
    stmt = stmt.where(MarketPrice.price_date <= (to_date or date.today()))
    if commodity_id:
        stmt = stmt.where(MarketPrice.commodity_id == commodity_id)
    if market_id:
        stmt = stmt.where(MarketPrice.market_id == market_id)
    if district:
        stmt = stmt.where(Market.district == district)
    if market_type:
        stmt = stmt.where(Market.market_type == market_type)
    if min_price is not None:
        stmt = stmt.where(MarketPrice.modal_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(MarketPrice.modal_price <= max_price)
    return stmt.order_by(MarketPrice.price_date.desc(), MarketPrice.modal_price.desc())
