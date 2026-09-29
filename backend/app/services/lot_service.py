"""Farm lot (sale inventory) service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import LotStatus, NotificationType, SellerType
from app.core.exceptions import (
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.models import Commodity, FarmLot, LotImage, MarketPrice, Offer, User
from app.repositories.markets import CommodityRepository, MarketPriceRepository
from app.repositories.trade import LotRepository, OfferRepository
from app.schemas.trade import FarmLotCreate, FarmLotUpdate, LotImageCreate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.codes import lot_code
from app.utils.geo import district_coords, haversine_km

logger = get_logger(__name__)

EDITABLE_STATUSES = {LotStatus.DRAFT, LotStatus.PUBLISHED, LotStatus.UNDER_OFFER}
RESERVED_FOR_BUYER = {LotStatus.SOLD, LotStatus.IN_TRANSIT, LotStatus.COMPLETED}


class LotService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.lots = LotRepository(FarmLot, session)
        self.offers = OfferRepository(Offer, session)
        self.commodities = CommodityRepository(Commodity, session)
        self.prices = MarketPriceRepository(MarketPrice, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    # ------------------------------------------------------------- helpers
    def get_lot(self, lot_id: uuid.UUID) -> FarmLot:
        lot = self.lots.get_detailed(lot_id)
        if lot is None or lot.is_deleted:
            raise NotFoundError("The requested lot could not be found.", code="LOT_NOT_FOUND")
        return lot

    def assert_owner(self, lot: FarmLot, user: User) -> None:
        if lot.seller_user_id != user.id:
            raise PermissionDeniedError(
                "You can only manage lots that you created.", code="LOT_NOT_OWNER"
            )

    def seller_type_for(self, user: User) -> SellerType:
        return SellerType.FPO if user.role.value == "FPO" else SellerType.FARMER

    def _resolve_location(
        self, user: User, payload: FarmLotCreate
    ) -> tuple[str | None, float | None, float | None]:
        district = payload.district or user.district
        lat, lon = payload.latitude, payload.longitude
        if lat is None or lon is None:
            profile_district = district
            if user.farmer_profile and user.farmer_profile.district:
                profile_district = user.farmer_profile.district
            elif user.fpo_profile and user.fpo_profile.district:
                profile_district = user.fpo_profile.district
            c_lat, c_lon = district_coords(profile_district)
            lat = lat if lat is not None else c_lat
            lon = lon if lon is not None else c_lon
        return district, lat, lon

    # ------------------------------------------------------------- queries
    def list_lots(
        self,
        *,
        seller_user_id: uuid.UUID | None = None,
        status: Sequence[LotStatus] | None = None,
        commodity_id: uuid.UUID | None = None,
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
        sort: str = "-created_at",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FarmLot], int]:
        if seller_user_id is None and not status:
            status = [LotStatus.PUBLISHED, LotStatus.UNDER_OFFER]
        stmt = self.lots.browse_query(
            status=status,
            commodity_id=commodity_id,
            seller_user_id=seller_user_id,
            district=district,
            taluka=taluka,
            min_grade=min_grade,
            available_from=available_from,
            available_to=available_to,
            min_quantity=min_quantity,
            max_price=max_price,
            term=term,
            organic_only=organic_only,
            exclude_seller_id=exclude_seller_id,
        )
        for token in [sort, "created_at"]:
            descending = token.startswith("-")
            field = token.lstrip("-")
            column = getattr(FarmLot, field, None)
            if column is not None:
                stmt = stmt.order_by(column.desc() if descending else column.asc())
        return self.lots.paginate(stmt=stmt, page=page, page_size=page_size)

    def status_counts(self, seller_user_id: uuid.UUID) -> dict[LotStatus, int]:
        return self.lots.status_counts_for_user(seller_user_id)

    # ----------------------------------------------------------- mutations
    def create_lot(self, payload: FarmLotCreate, user: User) -> FarmLot:
        commodity = self.commodities.get(payload.commodity_id)
        if commodity is None or not commodity.is_active:
            raise NotFoundError("Commodity not found.", code="COMMODITY_NOT_FOUND")
        if payload.unit not in (commodity.permitted_units or ["quintal"]):
            raise ConflictError(
                f"{commodity.name} is traded in {', '.join(commodity.permitted_units)}.",
                code="INVALID_UNIT",
            )
        district, lat, lon = self._resolve_location(user, payload)
        lot = FarmLot(
            seller_type=self.seller_type_for(user),
            seller_user_id=user.id,
            commodity_id=commodity.id,
            lot_code=lot_code(),
            title=payload.title.strip(),
            description=payload.description,
            quantity=payload.quantity,
            available_quantity=payload.quantity,
            unit=payload.unit,
            expected_price=payload.expected_price,
            minimum_price=payload.minimum_price,
            quality_grade=payload.quality_grade,
            quality_specs=payload.quality_specs or {},
            harvest_date=payload.harvest_date,
            available_from=payload.available_from or date.today(),
            village=payload.village,
            taluka=payload.taluka,
            district=district,
            latitude=lat,
            longitude=lon,
            pincode=payload.pincode,
            storage_available=payload.storage_available,
            organic_certified=payload.organic_certified,
            pickup_available=payload.pickup_available,
            seller_handles_transport=payload.seller_handles_transport,
            status=LotStatus.PUBLISHED if payload.publish_now else LotStatus.DRAFT,
        )
        if lot.status is LotStatus.PUBLISHED:
            from datetime import UTC, datetime

            lot.published_at = datetime.now(UTC)
        self.session.add(lot)
        self.session.flush()
        for image in payload.images:
            self._add_image(lot.id, image)
        self.session.flush()
        self.audit.record(
            action="LOT_CREATED",
            entity_type="farm_lot",
            entity_id=lot.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={"lot_code": lot.lot_code, "quantity": lot.quantity, "status": lot.status.value},
        )
        logger.info("lot.created", lot_id=str(lot.id), seller=str(user.id))
        return self.get_lot(lot.id)

    def _add_image(self, lot_id: uuid.UUID, image: LotImageCreate) -> LotImage:
        return LotImage(
            lot_id=lot_id,
            url=image.url,
            caption=image.caption,
            is_primary=image.is_primary,
        )

    def update_lot(self, lot_id: uuid.UUID, payload: FarmLotUpdate, user: User) -> FarmLot:
        lot = self.get_lot(lot_id)
        self.assert_owner(lot, user)
        if lot.status not in EDITABLE_STATUSES:
            raise InvalidStateTransitionError(
                f"A lot in {lot.status.value} state can no longer be edited.",
                code="LOT_NOT_EDITABLE",
            )
        data = payload.model_dump(exclude_unset=True)
        images = data.pop("images", None)
        before = {
            "status": lot.status.value,
            "quantity": lot.quantity,
            "available_quantity": lot.available_quantity,
            "expected_price": lot.expected_price,
        }
        for key, value in data.items():
            if hasattr(lot, key):
                setattr(lot, key, value)
        if images is not None:
            for existing in list(lot.images or []):
                self.session.delete(existing)
            self.session.flush()
            for image in images:
                self.session.add(self._add_image(lot.id, image))
        self.session.flush()
        self.audit.record(
            action="LOT_UPDATED",
            entity_type="farm_lot",
            entity_id=lot.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before=before,
            after={
                "status": lot.status.value,
                "quantity": lot.quantity,
                "available_quantity": lot.available_quantity,
                "expected_price": lot.expected_price,
            },
        )
        return self.get_lot(lot_id)

    def publish_lot(self, lot_id: uuid.UUID, user: User) -> FarmLot:
        from datetime import UTC, datetime

        lot = self.get_lot(lot_id)
        self.assert_owner(lot, user)
        if lot.status is LotStatus.PUBLISHED:
            return lot
        if lot.status is not LotStatus.DRAFT:
            raise InvalidStateTransitionError(
                f"Only draft lots can be published (current status: {lot.status.value}).",
                code="LOT_NOT_PUBLISHABLE",
            )
        if lot.available_quantity <= 0:
            raise ConflictError("This lot has no remaining quantity to sell.", code="LOT_EMPTY")
        lot.status = LotStatus.PUBLISHED
        lot.published_at = datetime.now(UTC)
        self.session.flush()
        self.audit.record(
            action="LOT_PUBLISHED",
            entity_type="farm_lot",
            entity_id=lot.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={"status": lot.status.value},
        )
        commodity_name = lot.commodity.name if lot.commodity else "produce"
        self.notifications.notify(
            user.id,
            notification_type=NotificationType.LOT_UPDATE,
            title=f"Lot {lot.lot_code} is now live",
            body=(
                f"{lot.available_quantity:,.0f} {lot.unit} of {commodity_name} "
                f"is visible to verified buyers."
            ),
            link="/my-lots",
        )
        return self.get_lot(lot_id)

    def cancel_lot(self, lot_id: uuid.UUID, user: User, *, reason: str | None = None) -> FarmLot:
        lot = self.get_lot(lot_id)
        self.assert_owner(lot, user)
        if lot.status in RESERVED_FOR_BUYER:
            raise InvalidStateTransitionError(
                "A sold or in-transit lot cannot be cancelled. Raise a grievance instead.",
                code="LOT_LOCKED",
            )
        before = lot.status.value
        lot.status = LotStatus.CANCELLED
        for offer in self.offers.active_for_lot(lot.id):
            from app.core.enums import OfferStatus

            offer.status = OfferStatus.REJECTED
            offer.decline_reason = "Lot withdrawn by the seller"
            self.notifications.notify(
                offer.buyer_user_id,
                notification_type=NotificationType.OFFER_REJECTED,
                title=f"Offer on lot {lot.lot_code} withdrawn",
                body="The seller withdrew this lot. Your offer is no longer active.",
                link="/offers",
            )
        self.session.flush()
        self.audit.record(
            action="LOT_CANCELLED",
            entity_type="farm_lot",
            entity_id=lot.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before={"status": before},
            after={"status": lot.status.value},
            note=reason,
        )
        return self.get_lot(lot_id)

    def delete_lot(self, lot_id: uuid.UUID, user: User) -> None:
        lot = self.get_lot(lot_id)
        self.assert_owner(lot, user)
        if lot.status not in EDITABLE_STATUSES or self.offers.pending_count_for_lot(lot.id) > 0:
            raise ConflictError(
                "Lots with active offers or completed sales cannot be deleted.",
                code="LOT_NOT_DELETABLE",
            )
        self.lots.delete(lot)
        self.audit.record(
            action="LOT_DELETED",
            entity_type="farm_lot",
            entity_id=lot.id,
            actor_user_id=user.id,
            actor_role=user.role,
        )

    def mark_under_offer(self, lot: FarmLot) -> None:
        if lot.status is LotStatus.PUBLISHED and self.offers.pending_count_for_lot(lot.id) > 0:
            lot.status = LotStatus.UNDER_OFFER
            self.session.flush()

    def refresh_offer_counters(self, lot_id: uuid.UUID) -> None:
        lot = self.lots.get(lot_id)
        if lot is None:
            return
        lot.active_offers_count = self.offers.pending_count_for_lot(lot_id)

    def increment_views(self, lot_id: uuid.UUID) -> None:
        lot = self.lots.get(lot_id)
        if lot is not None:
            lot.view_count = (lot.view_count or 0) + 1
            self.session.flush()

    # ------------------------------------------------------- presentation
    def enrich(
        self,
        lot: FarmLot,
        *,
        origin_latitude: float | None = None,
        origin_longitude: float | None = None,
    ) -> dict[str, Any]:
        from app.schemas.trade import LotImageOut, LotSellerOut

        seller = lot.seller
        fpo = getattr(seller, "fpo_profile", None) if seller else None
        buyer_profile = getattr(seller, "buyer_profile", None) if seller else None
        completed_orders = 0
        if seller is not None:
            from app.core.enums import OrderStatus
            from app.models import Order
            from app.repositories.trade import OrderRepository

            repo = OrderRepository(Order, self.session)
            completed_orders = int(
                repo.count(
                    seller_user_id=seller.id,
                    status=[
                        OrderStatus.QUALITY_CONFIRMED,
                        OrderStatus.PAYMENT_COMPLETED,
                        OrderStatus.COMPLETED,
                    ],
                )
            )
        latest_price = None
        price_market = None
        if lot.commodity_id:
            prices = self.prices.latest_by_commodity(lot.commodity_id, date.today())
            for price in prices:
                if price.market is not None and price.market.district == lot.district:
                    latest_price = price.modal_price
                    price_market = price.market.name
                    break
            if latest_price is None and prices and prices[0].market is not None:
                latest_price = prices[0].modal_price
                price_market = prices[0].market.name
        distance = None
        if origin_latitude is not None and lot.latitude is not None:
            distance = haversine_km(
                origin_latitude, origin_longitude or 0.0, lot.latitude, lot.longitude or 0.0
            )
        from datetime import UTC, datetime

        from app.core.enums import InspectionStatus

        inspection_grade = None
        confirmed = [
            i
            for i in (lot.inspections or [])
            if getattr(i, "status", None) is InspectionStatus.CONFIRMED
        ]
        if confirmed:
            latest = max(confirmed, key=lambda i: i.created_at or datetime.min.replace(tzinfo=UTC))
            inspection_grade = latest.grade
        return {
            "id": lot.id,
            "lot_code": lot.lot_code,
            "seller_type": lot.seller_type,
            "seller_user_id": lot.seller_user_id,
            "commodity_id": lot.commodity_id,
            "commodity_name": lot.commodity.name if lot.commodity else None,
            "commodity_category": lot.commodity.category if lot.commodity else None,
            "title": lot.title,
            "description": lot.description,
            "quantity": lot.quantity,
            "available_quantity": lot.available_quantity,
            "unit": lot.unit,
            "expected_price": lot.expected_price,
            "minimum_price": lot.minimum_price,
            "quality_grade": lot.quality_grade,
            "quality_specs": lot.quality_specs or {},
            "harvest_date": lot.harvest_date,
            "available_from": lot.available_from,
            "village": lot.village,
            "taluka": lot.taluka,
            "district": lot.district,
            "state": lot.state,
            "latitude": lot.latitude,
            "longitude": lot.longitude,
            "storage_available": lot.storage_available,
            "organic_certified": lot.organic_certified,
            "pickup_available": lot.pickup_available,
            "seller_handles_transport": lot.seller_handles_transport,
            "status": lot.status,
            "published_at": lot.published_at,
            "view_count": lot.view_count,
            "active_offers_count": lot.active_offers_count,
            "created_at": lot.created_at,
            "updated_at": lot.updated_at,
            "images": [LotImageOut.model_validate(i) for i in (lot.images or [])],
            "seller": LotSellerOut(
                id=seller.id if seller else lot.seller_user_id,
                full_name=seller.full_name if seller else "Unknown",
                role=seller.primary_role.name.value if seller and seller.primary_role else "FARMER",
                district=lot.district,
                taluka=lot.taluka,
                village=lot.village,
                organisation_name=(
                    fpo.organisation_name
                    if fpo
                    else (buyer_profile.organisation_name if buyer_profile else None)
                ),
                member_count=fpo.member_count if fpo else None,
                phone=seller.phone if seller else None,
                is_verified_seller=bool(fpo and fpo.member_count and fpo.member_count > 0),
                completed_orders=completed_orders,
                rating=round(min(5.0, 3.6 + completed_orders * 0.12), 1),
            ),
            "latest_market_price": latest_price,
            "market_price_source_market": price_market,
            "distance_km": distance,
            "inspection_grade": inspection_grade,
        }

    def similar_lots(self, lot_id: uuid.UUID, limit: int = 6) -> list[FarmLot]:
        lot = self.get_lot(lot_id)
        return self.lots.similar_active(lot, limit=limit)
