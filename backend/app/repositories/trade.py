"""Trade repositories: lots, demands, offers, orders, transactions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.core.enums import (
    DemandStatus,
    LotStatus,
    OfferStatus,
    OrderStatus,
    SellerType,
    UserRole,
)
from app.models import (
    BuyerDemand,
    BuyerProfile,
    Commodity,
    FarmLot,
    Offer,
    Order,
    Transaction,
    User,
)
from app.repositories.base import BaseRepository


class LotRepository(BaseRepository[FarmLot]):
    def _with_refs(self) -> Select:
        return self._base_query().options(
            joinedload(FarmLot.commodity),
            selectinload(FarmLot.images),
            joinedload(FarmLot.seller).selectinload(User.primary_role),
            joinedload(FarmLot.seller).selectinload(User.farmer_profile),
            joinedload(FarmLot.seller).selectinload(User.fpo_profile),
            selectinload(FarmLot.inspections),
        )

    def get_detailed(self, lot_id: uuid.UUID) -> FarmLot | None:
        return (
            self.session.execute(self._with_refs().where(FarmLot.id == lot_id))
            .unique()
            .scalar_one_or_none()
        )

    def browse_query(
        self,
        *,
        status: Sequence[LotStatus] | None = None,
        commodity_id: uuid.UUID | None = None,
        seller_user_id: uuid.UUID | None = None,
        seller_type: SellerType | None = None,
        district: str | None = None,
        taluka: str | None = None,
        min_grade: str | None = None,
        available_from: date | None = None,
        available_to: date | None = None,
        min_quantity: float | None = None,
        max_price: float | None = None,
        term: str | None = None,
        organic_only: bool = False,
        exclude_seller_id: uuid.UUID | None = None,
    ) -> Select:
        stmt = self._with_refs()
        if status:
            stmt = stmt.where(FarmLot.status.in_(list(status)))
        if commodity_id:
            stmt = stmt.where(FarmLot.commodity_id == commodity_id)
        if seller_user_id:
            stmt = stmt.where(FarmLot.seller_user_id == seller_user_id)
        if seller_type:
            stmt = stmt.where(FarmLot.seller_type == seller_type)
        if district:
            stmt = stmt.where(FarmLot.district == district)
        if taluka:
            stmt = stmt.where(FarmLot.taluka == taluka)
        if min_grade:
            stmt = stmt.where(FarmLot.quality_grade == min_grade)
        if available_from:
            stmt = stmt.where(
                or_(FarmLot.available_from.is_(None), FarmLot.available_from >= available_from)
            )
        if available_to:
            stmt = stmt.where(
                or_(FarmLot.available_from.is_(None), FarmLot.available_from <= available_to)
            )
        if min_quantity:
            stmt = stmt.where(FarmLot.available_quantity >= min_quantity)
        if max_price is not None:
            stmt = stmt.where(
                or_(FarmLot.minimum_price.is_(None), FarmLot.minimum_price <= max_price)
            )
        if organic_only:
            stmt = stmt.where(FarmLot.organic_certified.is_(True))
        if exclude_seller_id:
            stmt = stmt.where(FarmLot.seller_user_id != exclude_seller_id)
        if term:
            pattern = f"%{term.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(FarmLot.title).like(pattern),
                    func.lower(FarmLot.lot_code).like(pattern),
                    func.lower(func.coalesce(FarmLot.description, "")).like(pattern),
                )
            )
        return stmt

    def status_counts_for_user(self, seller_user_id: uuid.UUID) -> dict[LotStatus, int]:
        stmt = (
            select(FarmLot.status, func.count(FarmLot.id))
            .where(FarmLot.seller_user_id == seller_user_id, FarmLot.is_deleted.is_(False))
            .group_by(FarmLot.status)
        )
        return {status: int(count) for status, count in self.session.execute(stmt).all()}

    def active_for_seller(self, seller_user_id: uuid.UUID) -> list[FarmLot]:
        return self.find_all(
            filters={
                "seller_user_id": seller_user_id,
                "status": [
                    LotStatus.PUBLISHED,
                    LotStatus.UNDER_OFFER,
                    LotStatus.SOLD,
                    LotStatus.IN_TRANSIT,
                ],
            },
            order_by=["-updated_at"],
            limit=50,
        )

    def similar_active(self, lot: FarmLot, *, limit: int = 6) -> list[FarmLot]:
        stmt = (
            self._with_refs()
            .where(
                FarmLot.commodity_id == lot.commodity_id,
                FarmLot.id != lot.id,
                FarmLot.status == LotStatus.PUBLISHED,
            )
            .order_by(FarmLot.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).unique().scalars().all())


class DemandRepository(BaseRepository[BuyerDemand]):
    def _with_refs(self) -> Select:
        return self._base_query().options(
            joinedload(BuyerDemand.commodity),
            joinedload(BuyerDemand.buyer).joinedload(BuyerProfile.user),
        )

    def get_detailed(self, demand_id: uuid.UUID) -> BuyerDemand | None:
        return (
            self.session.execute(self._with_refs().where(BuyerDemand.id == demand_id))
            .unique()
            .scalar_one_or_none()
        )

    def search_query(
        self,
        *,
        status: Sequence[DemandStatus] | None = None,
        commodity_id: uuid.UUID | None = None,
        district: str | None = None,
        buyer_user_id: uuid.UUID | None = None,
        required_by_before: date | None = None,
        required_by_after: date | None = None,
        min_grade: str | None = None,
        min_quantity: float | None = None,
        term: str | None = None,
    ) -> Select:
        stmt = self._with_refs()
        if status:
            stmt = stmt.where(BuyerDemand.status.in_(list(status)))
        if commodity_id:
            stmt = stmt.where(BuyerDemand.commodity_id == commodity_id)
        if district:
            stmt = stmt.where(BuyerDemand.district == district)
        if buyer_user_id:
            stmt = stmt.where(BuyerDemand.buyer_user_id == buyer_user_id)
        if required_by_before:
            stmt = stmt.where(BuyerDemand.required_by_date <= required_by_before)
        if required_by_after:
            stmt = stmt.where(BuyerDemand.required_by_date >= required_by_after)
        if min_grade:
            stmt = stmt.where(BuyerDemand.min_grade == min_grade)
        if min_quantity:
            stmt = stmt.where(
                BuyerDemand.required_quantity - BuyerDemand.fulfilled_quantity >= min_quantity
            )
        if term:
            pattern = f"%{term.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(BuyerDemand.delivery_location).like(pattern),
                    func.lower(BuyerDemand.reference_code).like(pattern),
                    func.lower(func.coalesce(BuyerDemand.notes, "")).like(pattern),
                )
            )
        return stmt

    def open_demands_for_commodity(self, commodity_id: uuid.UUID) -> list[BuyerDemand]:
        return list(
            self.session.execute(
                self._with_refs()
                .where(
                    BuyerDemand.commodity_id == commodity_id,
                    BuyerDemand.status.in_([DemandStatus.OPEN, DemandStatus.PARTIALLY_FULFILLED]),
                    BuyerDemand.required_by_date >= date.today(),
                )
                .order_by(BuyerDemand.required_by_date.asc())
            )
            .unique()
            .scalars()
            .all()
        )

    def aggregate_demand(self, *, days: int = 30) -> dict[uuid.UUID, float]:
        from datetime import timedelta

        since = date.today() - timedelta(days=days)
        stmt = (
            select(BuyerDemand.commodity_id, func.sum(BuyerDemand.required_quantity))
            .where(
                BuyerDemand.status.in_([DemandStatus.OPEN, DemandStatus.PARTIALLY_FULFILLED]),
                BuyerDemand.required_by_date >= since,
            )
            .group_by(BuyerDemand.commodity_id)
        )
        return {row[0]: float(row[1] or 0) for row in self.session.execute(stmt).all()}


class OfferRepository(BaseRepository[Offer]):
    def _with_refs(self) -> Select:
        return self._base_query().options(
            joinedload(Offer.lot).joinedload(FarmLot.commodity),
            joinedload(Offer.buyer).joinedload(User.buyer_profile),
            joinedload(Offer.buyer).joinedload(User.fpo_profile),
        )

    def get_detailed(self, offer_id: uuid.UUID) -> Offer | None:
        return (
            self.session.execute(self._with_refs().where(Offer.id == offer_id))
            .unique()
            .scalar_one_or_none()
        )

    def active_for_lot(self, lot_id: uuid.UUID) -> list[Offer]:
        return list(
            self.session.execute(
                self._with_refs()
                .where(
                    Offer.lot_id == lot_id,
                    Offer.status == OfferStatus.PENDING,
                    Offer.is_active.is_(True),
                )
                .order_by(Offer.offered_price.desc())
            )
            .unique()
            .scalars()
            .all()
        )

    def for_seller(self, seller_user_id: uuid.UUID) -> Select:
        return (
            self._with_refs()
            .join(FarmLot, FarmLot.id == Offer.lot_id)
            .where(FarmLot.seller_user_id == seller_user_id)
        )

    def for_buyer(self, buyer_user_id: uuid.UUID) -> Select:
        return self._with_refs().where(Offer.buyer_user_id == buyer_user_id)

    def negotiation_chain(self, offer_id: uuid.UUID) -> list[Offer]:
        stmt = (
            self._with_refs()
            .where(or_(Offer.id == offer_id, Offer.parent_offer_id == offer_id))
            .order_by(Offer.created_at.asc())
        )
        return list(self.session.execute(stmt).unique().scalars().all())

    def pending_count_for_lot(self, lot_id: uuid.UUID) -> int:
        return self.count(lot_id=lot_id, status=OfferStatus.PENDING, is_active=True)


class OrderRepository(BaseRepository[Order]):
    def _with_refs(self) -> Select:
        return self._base_query().options(
            joinedload(Order.commodity),
            joinedload(Order.buyer).joinedload(User.buyer_profile),
            joinedload(Order.seller).joinedload(User.fpo_profile),
            joinedload(Order.seller).joinedload(User.farmer_profile),
            selectinload(Order.logistics_request),
            selectinload(Order.transaction).selectinload(Transaction.payments),
            selectinload(Order.inspections),
        )

    def get_detailed(self, order_id: uuid.UUID) -> Order | None:
        return (
            self.session.execute(self._with_refs().where(Order.id == order_id))
            .unique()
            .scalar_one_or_none()
        )

    def search_query(
        self,
        *,
        user_id: uuid.UUID | None = None,
        user_role: UserRole | None = None,
        status: Sequence[OrderStatus] | None = None,
        commodity_id: uuid.UUID | None = None,
        district: str | None = None,
    ) -> Select:
        stmt = self._with_refs()
        if user_id:
            if user_role is UserRole.BUYER:
                stmt = stmt.where(Order.buyer_user_id == user_id)
            elif user_role in (UserRole.FARMER, UserRole.FPO):
                stmt = stmt.where(Order.seller_user_id == user_id)
            elif user_role in (UserRole.LOGISTICS_PARTNER, UserRole.QUALITY_INSPECTOR):
                # Staff act on either side of a trade, so they see the orders they
                # are actually working rather than an arbitrary seller-side slice.
                stmt = stmt.where(
                    or_(Order.seller_user_id == user_id, Order.buyer_user_id == user_id)
                )
            else:
                # ADMIN (and any other role) without an explicit scope sees
                # everything rather than silently seeing nothing.
                pass
        if status:
            stmt = stmt.where(Order.status.in_(list(status)))
        if commodity_id:
            stmt = stmt.where(Order.commodity_id == commodity_id)
        if district:
            stmt = stmt.where(
                or_(Order.pickup_district == district, Order.delivery_district == district)
            )
        return stmt

    def pipeline_counts(self) -> list[tuple[OrderStatus, int, float]]:
        """Platform-wide status funnel, for the administrator dashboard."""
        return self._pipeline_counts_for(None, None)

    def pipeline_counts_for_user(
        self, user_id: uuid.UUID, user_role: UserRole | None = None
    ) -> list[tuple[OrderStatus, int, float]]:
        """Status funnel scoped to one user's side of the trade."""
        return self._pipeline_counts_for(user_id, user_role)

    def _pipeline_counts_for(
        self, user_id: uuid.UUID | None, user_role: UserRole | None
    ) -> list[tuple[OrderStatus, int, float]]:
        stmt = select(
            Order.status,
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_value), 0.0),
        )
        if user_id is not None:
            if user_role is UserRole.BUYER:
                stmt = stmt.where(Order.buyer_user_id == user_id)
            elif user_role in (UserRole.FARMER, UserRole.FPO):
                stmt = stmt.where(Order.seller_user_id == user_id)
            elif user_role in (UserRole.LOGISTICS_PARTNER, UserRole.QUALITY_INSPECTOR):
                stmt = stmt.where(
                    or_(Order.seller_user_id == user_id, Order.buyer_user_id == user_id)
                )
        stmt = stmt.group_by(Order.status)
        return [
            (status, int(count), float(value or 0))
            for status, count, value in self.session.execute(stmt).all()
        ]

    def trade_value_since(self, days: int = 30) -> float:
        from datetime import UTC, datetime, timedelta

        since = datetime.now(UTC) - timedelta(days=days)
        stmt = select(func.coalesce(func.sum(Order.total_value), 0.0)).where(
            Order.created_at >= since
        )
        return float(self.session.execute(stmt).scalar_one() or 0.0)


class TransactionRepository(BaseRepository[Transaction]):
    def _with_refs(self) -> Select:
        # No ``commodity`` relationship on Transaction; views read commodity_id.
        return self._base_query().options(
            joinedload(Transaction.order),
            selectinload(Transaction.payments),
        )

    def get_detailed(self, transaction_id: uuid.UUID) -> Transaction | None:
        return (
            self.session.execute(self._with_refs().where(Transaction.id == transaction_id))
            .unique()
            .scalar_one_or_none()
        )

    def for_user(self, user_id: uuid.UUID, *, as_buyer: bool = False) -> Select:
        column = Transaction.buyer_user_id if as_buyer else Transaction.seller_user_id
        return self._with_refs().where(column == user_id)

    def totals_for_user(self, user_id: uuid.UUID, *, as_buyer: bool = False) -> dict[str, float]:
        column = Transaction.buyer_user_id if as_buyer else Transaction.seller_user_id
        stmt = select(
            func.coalesce(func.sum(Transaction.total_amount), 0.0),
            func.count(Transaction.id),
        ).where(column == user_id)
        total, count = self.session.execute(stmt).one()
        return {"total": float(total or 0), "count": int(count)}

    def district_trade_value(self, days: int = 90) -> list[tuple[str, float]]:
        from datetime import UTC, datetime, timedelta

        since = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(Transaction.district, func.coalesce(func.sum(Transaction.total_amount), 0.0))
            .where(Transaction.district.isnot(None), Transaction.created_at >= since)
            .group_by(Transaction.district)
            .order_by(func.coalesce(func.sum(Transaction.total_amount), 0.0).desc())
        )
        return [
            (district, float(value or 0)) for district, value in self.session.execute(stmt).all()
        ]


def lots_for_matching(
    repo: LotRepository,
    *,
    commodity_id: uuid.UUID,
    exclude_seller_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[FarmLot]:
    stmt = repo.browse_query(
        status=[LotStatus.PUBLISHED, LotStatus.UNDER_OFFER],
        commodity_id=commodity_id,
        exclude_seller_id=exclude_seller_id,
    ).limit(limit)
    return list(repo.session.execute(stmt).unique().scalars().all())


def demands_for_matching(
    repo: DemandRepository,
    *,
    commodity_id: uuid.UUID,
    buyer_user_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[BuyerDemand]:
    stmt = repo.search_query(
        status=[DemandStatus.OPEN, DemandStatus.PARTIALLY_FULFILLED],
        commodity_id=commodity_id,
        buyer_user_id=buyer_user_id,
    ).limit(limit)
    return list(repo.session.execute(stmt).unique().scalars().all())


def commodity_map(session, commodity_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Commodity]:
    if not commodity_ids:
        return {}
    stmt = select(Commodity).where(Commodity.id.in_(list(commodity_ids)))
    return {c.id: c for c in session.execute(stmt).scalars().all()}


def lots_with_offers(
    repo: LotRepository, lot_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[Offer]]:
    if not lot_ids:
        return {}
    stmt = select(Offer).where(
        and_(Offer.lot_id.in_(list(lot_ids)), Offer.status == OfferStatus.PENDING)
    )
    result: dict[uuid.UUID, list[Offer]] = {}
    for offer in repo.session.execute(stmt).scalars().all():
        result.setdefault(offer.lot_id, []).append(offer)
    return result
