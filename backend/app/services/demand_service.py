"""Buyer demand service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import DemandStatus, LotStatus, NotificationType, VerificationStatus
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.models import BuyerDemand, Commodity, FarmLot, User
from app.repositories.markets import CommodityRepository
from app.repositories.trade import DemandRepository, LotRepository
from app.schemas.trade import BuyerDemandCreate, BuyerDemandUpdate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.codes import demand_code
from app.utils.geo import district_coords

logger = get_logger(__name__)

OPEN_STATUSES = (DemandStatus.OPEN, DemandStatus.PARTIALLY_FULFILLED)


class DemandService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.demands = DemandRepository(BuyerDemand, session)
        self.lots = LotRepository(FarmLot, session)
        self.commodities = CommodityRepository(Commodity, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    def get_demand(self, demand_id: uuid.UUID) -> BuyerDemand:
        demand = self.demands.get_detailed(demand_id)
        if demand is None or demand.is_deleted:
            raise NotFoundError("The requested demand could not be found.", code="DEMAND_NOT_FOUND")
        return demand

    def assert_owner(self, demand: BuyerDemand, user: User) -> None:
        if demand.buyer_user_id != user.id:
            raise PermissionDeniedError(
                "You can only manage your own purchase requirements.", code="DEMAND_NOT_OWNER"
            )

    def list_demands(
        self,
        *,
        buyer_user_id: uuid.UUID | None = None,
        status: Sequence[DemandStatus] | None = None,
        commodity_id: uuid.UUID | None = None,
        district: str | None = None,
        min_grade: str | None = None,
        required_by_before: date | None = None,
        required_by_after: date | None = None,
        min_quantity: float | None = None,
        term: str | None = None,
        sort: str = "-created_at",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[BuyerDemand], int]:
        if buyer_user_id is None and not status:
            status = list(OPEN_STATUSES)
        stmt = self.demands.search_query(
            status=status,
            commodity_id=commodity_id,
            district=district,
            buyer_user_id=buyer_user_id,
            required_by_before=required_by_before,
            required_by_after=required_by_after,
            min_grade=min_grade,
            min_quantity=min_quantity,
            term=term,
        )
        for token in [sort, "created_at"]:
            descending = token.startswith("-")
            field = token.lstrip("-")
            column = getattr(BuyerDemand, field, None)
            if column is not None:
                stmt = stmt.order_by(column.desc() if descending else column.asc())
        return self.demands.paginate(stmt=stmt, page=page, page_size=page_size)

    def create_demand(self, payload: BuyerDemandCreate, user: User) -> BuyerDemand:
        commodity = self.commodities.get(payload.commodity_id)
        if commodity is None or not commodity.is_active:
            raise NotFoundError("Commodity not found.", code="COMMODITY_NOT_FOUND")
        if payload.required_by_date < date.today():
            raise ConflictError(
                "The required-by date cannot be in the past.", code="INVALID_REQUIRED_DATE"
            )
        lat, lon = payload.latitude, payload.longitude
        if lat is None or lon is None:
            c_lat, c_lon = district_coords(payload.district)
            lat = lat if lat is not None else c_lat
            lon = lon if lon is not None else c_lon
        demand = BuyerDemand(
            buyer_user_id=user.id,
            commodity_id=commodity.id,
            reference_code=demand_code(),
            required_quantity=payload.required_quantity,
            unit=payload.unit,
            min_grade=payload.min_grade,
            quality_specs=payload.quality_specs or {},
            min_price_per_unit=payload.min_price_per_unit,
            max_price_per_unit=payload.max_price_per_unit,
            delivery_location=payload.delivery_location.strip(),
            district=payload.district or user.district,
            taluka=payload.taluka,
            city=payload.city,
            latitude=lat,
            longitude=lon,
            max_pickup_radius_km=payload.max_pickup_radius_km,
            required_by_date=payload.required_by_date,
            delivery_window_days=payload.delivery_window_days,
            payment_terms=payload.payment_terms,
            payment_terms_days=payload.payment_terms_days,
            requires_verified_buyer=payload.requires_verified_buyer,
            status=DemandStatus.OPEN,
            notes=payload.notes,
        )
        self.session.add(demand)
        self.session.flush()
        self.audit.record(
            action="DEMAND_CREATED",
            entity_type="buyer_demand",
            entity_id=demand.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={
                "reference_code": demand.reference_code,
                "commodity": commodity.name,
                "quantity": demand.required_quantity,
            },
        )
        logger.info(
            "demand.created",
            demand_id=str(demand.id),
            buyer=str(user.id),
            commodity=commodity.name,
        )
        return self.get_demand(demand.id)

    def update_demand(
        self, demand_id: uuid.UUID, payload: BuyerDemandUpdate, user: User
    ) -> BuyerDemand:
        demand = self.get_demand(demand_id)
        self.assert_owner(demand, user)
        if demand.status in (DemandStatus.FULFILLED, DemandStatus.CLOSED):
            from app.core.exceptions import InvalidStateTransitionError

            raise InvalidStateTransitionError(
                "A closed requirement can no longer be edited.", code="DEMAND_CLOSED"
            )
        data = payload.model_dump(exclude_unset=True)
        before = {"status": demand.status.value, "required_quantity": demand.required_quantity}
        for key, value in data.items():
            if hasattr(demand, key):
                setattr(demand, key, value)
        self.session.flush()
        self.audit.record(
            action="DEMAND_UPDATED",
            entity_type="buyer_demand",
            entity_id=demand.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before=before,
            after={"status": demand.status.value, "required_quantity": demand.required_quantity},
        )
        return self.get_demand(demand_id)

    def close_demand(
        self, demand_id: uuid.UUID, user: User, *, reason: str | None = None
    ) -> BuyerDemand:
        demand = self.get_demand(demand_id)
        self.assert_owner(demand, user)
        before = demand.status.value
        demand.status = DemandStatus.CLOSED
        self.session.flush()
        self.audit.record(
            action="DEMAND_CLOSED",
            entity_type="buyer_demand",
            entity_id=demand.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before={"status": before},
            after={"status": demand.status.value},
            note=reason,
        )
        return self.get_demand(demand_id)

    def expire_stale(self) -> int:
        stale = self.demands.find_all(
            filters={"status": [DemandStatus.OPEN, DemandStatus.PARTIALLY_FULFILLED]},
            limit=500,
        )
        count = 0
        for demand in stale:
            if demand.required_by_date < date.today():
                demand.status = DemandStatus.EXPIRED
                count += 1
        if count:
            self.session.flush()
            logger.info("demand.expired", count=count)
        return count

    def matched_lot_count(self, demand: BuyerDemand) -> int:
        stmt = self.lots.browse_query(commodity_id=demand.commodity_id).where(
            FarmLot.status.in_([LotStatus.PUBLISHED, LotStatus.UNDER_OFFER])
        )
        lots = self.session.execute(stmt).unique().scalars().all()
        return len(
            [
                lot
                for lot in lots
                if lot.available_quantity > 0
                and (lot.available_from or date.today()) <= demand.required_by_date
            ]
        )

    def enrich(self, demand: BuyerDemand) -> dict[str, Any]:
        profile = demand.buyer
        return {
            "id": demand.id,
            "reference_code": demand.reference_code,
            "buyer_user_id": demand.buyer_user_id,
            "buyer_name": profile.user.full_name if profile and profile.user else None,
            "buyer_organisation": profile.organisation_name if profile else None,
            "buyer_verified": bool(
                profile and profile.verification_status is VerificationStatus.VERIFIED
            ),
            "commodity_id": demand.commodity_id,
            "commodity_name": demand.commodity.name if demand.commodity else None,
            "required_quantity": demand.required_quantity,
            "fulfilled_quantity": demand.fulfilled_quantity,
            "unit": demand.unit,
            "min_grade": demand.min_grade,
            "quality_specs": demand.quality_specs or {},
            "min_price_per_unit": demand.min_price_per_unit,
            "max_price_per_unit": demand.max_price_per_unit,
            "delivery_location": demand.delivery_location,
            "district": demand.district,
            "taluka": demand.taluka,
            "city": demand.city,
            "latitude": demand.latitude,
            "longitude": demand.longitude,
            "max_pickup_radius_km": demand.max_pickup_radius_km,
            "required_by_date": demand.required_by_date,
            "delivery_window_days": demand.delivery_window_days,
            "payment_terms": demand.payment_terms,
            "payment_terms_days": demand.payment_terms_days,
            "requires_verified_buyer": demand.requires_verified_buyer,
            "status": demand.status,
            "notes": demand.notes,
            "active_offers_count": len(
                [o for o in (demand.offers or []) if o.status.value == "PENDING"]
            ),
            "matched_lots_count": self.matched_lot_count(demand),
            "created_at": demand.created_at,
        }

    def notify_sellers(self, demand: BuyerDemand, lot_ids: Sequence[uuid.UUID]) -> int:
        """Let sellers of matching lots know a new requirement was published."""
        if not lot_ids:
            return 0
        matching = (
            self.session.execute(
                self.lots.browse_query(commodity_id=demand.commodity_id).where(
                    FarmLot.id.in_(list(lot_ids))
                )
            )
            .unique()
            .scalars()
            .all()
        )
        commodity = demand.commodity.name if demand.commodity else "produce"
        for lot in matching:
            self.notifications.notify(
                lot.seller_user_id,
                notification_type=NotificationType.MARKET_INSIGHT,
                title=f"New buyer requirement for {commodity}",
                body=(
                    f"A buyer in {demand.delivery_location} needs "
                    f"{demand.required_quantity:,.0f} {demand.unit} of {commodity} "
                    f"({demand.min_grade.label}+) by {demand.required_by_date.isoformat()}."
                ),
                link="/demands",
                data={"demand_id": str(demand.id), "reference_code": demand.reference_code},
            )
        return len(matching)
