"""Offer service: buyer offers on lots, plus accept / reject / counter flow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import (
    LotStatus,
    NotificationType,
    OfferStatus,
    VerificationStatus,
)
from app.core.exceptions import (
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.models import BuyerDemand, FarmLot, Offer, Order, User
from app.repositories.trade import DemandRepository, LotRepository, OfferRepository
from app.schemas.trade import OfferCounter, OfferCreate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.order_service import OrderService
from app.utils.codes import offer_code
from app.utils.units import convert_quantity, normalise_unit

logger = get_logger(__name__)

DEFAULT_VALIDITY_HOURS = 48

GRADE_RANK: dict[str, int] = {"A": 3, "B": 2, "C": 1}


def _grade_rank(grade: str | None) -> int:
    return GRADE_RANK.get((grade or "").upper(), 0)


class OfferService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.offers = OfferRepository(Offer, session)
        self.lots = LotRepository(FarmLot, session)
        self.demands = DemandRepository(BuyerDemand, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)
        self.orders = OrderService(session)

    # ------------------------------------------------------------- helpers
    def get_offer(self, offer_id: uuid.UUID) -> Offer:
        offer = self.offers.get_detailed(offer_id)
        if offer is None:
            raise NotFoundError("The requested offer could not be found.", code="OFFER_NOT_FOUND")
        return offer

    def is_buyer(self, user: User) -> bool:
        return user.role.value == "BUYER"

    def is_seller(self, user: User) -> bool:
        return user.role.value in ("FARMER", "FPO")

    def _validate_offer_against_lot(
        self, payload: OfferCreate, lot: FarmLot, buyer: User
    ) -> list[str]:
        """Reject unworkable offers outright, but return advisory warnings otherwise."""
        if lot.status not in (LotStatus.PUBLISHED, LotStatus.UNDER_OFFER):
            raise InvalidStateTransitionError(
                f"Lot {lot.lot_code} is {lot.status.value.lower()} and is not accepting offers.",
                code="LOT_NOT_OPEN",
            )
        if lot.seller_user_id == buyer.id:
            raise PermissionDeniedError("You cannot make an offer on your own lot.")
        available = convert_quantity(lot.available_quantity, lot.unit, payload.unit)
        if payload.quantity > available:
            raise ConflictError(
                f"Only {lot.available_quantity:,.0f} {lot.unit} remain in this lot "
                f"(≈ {available:,.0f} {normalise_unit(payload.unit)}).",
                code="OFFER_QUANTITY_EXCEEDS_LOT",
            )
        warnings: list[str] = []
        if lot.minimum_price and payload.offered_price < lot.minimum_price:
            warnings.append(
                "Below the seller's minimum of "
                f"₹{lot.minimum_price:,.0f}/{normalise_unit(lot.unit)} — the seller is "
                "unlikely to accept, and they may counter instead."
            )
        if lot.quality_grade and _grade_rank(lot.quality_grade.value) < 3:
            warnings.append(
                f"This lot is graded {lot.quality_grade.value}. If your requirement is Grade A, "
                "ask the seller about a possible grade upgrade before committing."
            )
        if payload.payment_terms_days and payload.payment_terms_days > 30:
            warnings.append(
                f"Payment terms of {payload.payment_terms_days} days are longer than most buyers "
                "and FPOs accept; sellers may counter with shorter terms."
            )
        return warnings

    def preflight_offer(self, payload: OfferCreate, buyer: User) -> dict[str, Any]:
        """Non-mutating check the UI can call before a buyer submits an offer."""
        lot = self.lots.get_detailed(payload.lot_id)
        if lot is None or lot.is_deleted:
            raise NotFoundError("The requested lot could not be found.", code="LOT_NOT_FOUND")
        warnings = self._validate_offer_against_lot(payload, lot, buyer)
        return {
            "lot_id": str(lot.id),
            "lot_code": lot.lot_code,
            "available_quantity": lot.available_quantity,
            "unit": lot.unit,
            "minimum_price": lot.minimum_price,
            "asking_price": lot.expected_price,
            "can_submit": True,
            "warnings": warnings,
        }

    # -------------------------------------------------------------- create
    def create_offer(self, payload: OfferCreate, buyer: User) -> Offer:
        lot = self.lots.get_detailed(payload.lot_id)
        if lot is None or lot.is_deleted:
            raise NotFoundError("The requested lot could not be found.", code="LOT_NOT_FOUND")
        warnings = self._validate_offer_against_lot(payload, lot, buyer)
        demand: BuyerDemand | None = None
        if payload.demand_id:
            demand = self.demands.get_detailed(payload.demand_id)
            if demand is None or demand.buyer_user_id != buyer.id:
                raise PermissionDeniedError("That requirement does not belong to you.")
            if demand.commodity_id != lot.commodity_id:
                raise ConflictError(
                    "The requirement and the lot are for different commodities.",
                    code="DEMAND_COMMODITY_MISMATCH",
                )
        valid_until = payload.valid_until or (
            datetime.now(UTC) + timedelta(hours=DEFAULT_VALIDITY_HOURS)
        )
        offer = Offer(
            lot_id=lot.id,
            buyer_user_id=buyer.id,
            demand_id=demand.id if demand else None,
            reference_code=offer_code(),
            offered_price=payload.offered_price,
            quantity=payload.quantity,
            unit=payload.unit,
            delivery_terms=payload.delivery_terms,
            payment_terms=payload.payment_terms,
            payment_terms_days=payload.payment_terms_days,
            valid_until=valid_until,
            notes=payload.notes,
            status=OfferStatus.PENDING,
            is_active=True,
        )
        self.session.add(offer)
        self.session.flush()
        if lot.status is LotStatus.PUBLISHED:
            lot.status = LotStatus.UNDER_OFFER
        lot.active_offers_count = self.offers.pending_count_for_lot(lot.id)
        self.session.flush()
        self.audit.record(
            action="OFFER_CREATED",
            entity_type="offer",
            entity_id=offer.id,
            actor_user_id=buyer.id,
            actor_role=buyer.role,
            after={
                "reference_code": offer.reference_code,
                "lot_code": lot.lot_code,
                "offered_price": offer.offered_price,
                "quantity": offer.quantity,
                "warnings": warnings,
            },
        )
        for warning in warnings:
            logger.info("offer.advice", offer_id=str(offer.id), warning=warning)
        commodity = lot.commodity.name if lot.commodity else "produce"
        self.notifications.notify(
            lot.seller_user_id,
            notification_type=NotificationType.NEW_OFFER,
            title=f"New offer on {lot.lot_code}",
            body=(
                f"{buyer.full_name} offered "
                f"₹{offer.offered_price:,.0f}/{normalise_unit(offer.unit)} "
                f"for {offer.quantity:,.0f} {normalise_unit(offer.unit)} of {commodity}. "
                "Valid until "
                f"{offer.valid_until.isoformat() if offer.valid_until else 'further notice'}."
            ),
            link="/offers",
            data={"offer_id": str(offer.id), "lot_id": str(lot.id)},
        )
        logger.info("offer.created", offer_id=str(offer.id), lot=lot.lot_code)
        return self.get_offer(offer.id)

    # ------------------------------------------------------------- respond
    def accept(self, offer_id: uuid.UUID, user: User) -> Order:
        offer = self.get_offer(offer_id)
        lot = self.lots.get_detailed(offer.lot_id)
        if lot is None:
            raise NotFoundError("The linked lot no longer exists.", code="LOT_NOT_FOUND")
        if lot.seller_user_id != user.id and user.role.value != "ADMIN":
            raise PermissionDeniedError(
                "Only the seller can accept this offer.", code="OFFER_NOT_SELLER"
            )
        if offer.status is not OfferStatus.PENDING:
            raise InvalidStateTransitionError(
                f"This offer is already {offer.status.value.lower()}.", code="OFFER_NOT_PENDING"
            )
        if offer.valid_until and offer.valid_until < datetime.now(UTC):
            offer.status = OfferStatus.EXPIRED
            self.session.flush()
            raise InvalidStateTransitionError(
                "This offer expired before it was accepted.", code="OFFER_EXPIRED"
            )
        remaining = convert_quantity(lot.available_quantity, lot.unit, offer.unit)
        if offer.quantity > remaining:
            raise ConflictError(
                f"Only {remaining:,.0f} {normalise_unit(offer.unit)} remain in lot {lot.lot_code}.",
                code="OFFER_QUANTITY_EXCEEDS_LOT",
            )

        offer.status = OfferStatus.ACCEPTED
        offer.responded_at = datetime.now(UTC)
        offer.responded_by_user_id = user.id
        for sibling in self.offers.active_for_lot(lot.id):
            if sibling.id != offer.id and sibling.status is OfferStatus.PENDING:
                sibling.status = OfferStatus.REJECTED
                sibling.decline_reason = "Another offer was accepted for this lot"
                sibling.responded_at = datetime.now(UTC)
                sibling.responded_by_user_id = user.id
                self.notifications.notify(
                    sibling.buyer_user_id,
                    notification_type=NotificationType.OFFER_REJECTED,
                    title=f"Offer on {lot.lot_code} closed",
                    body="The seller accepted a different offer for this lot.",
                    link="/offers",
                )
        order = self.orders.create_from_offer(offer=offer, lot=lot, actor=user)
        self.audit.record(
            action="OFFER_ACCEPTED",
            entity_type="offer",
            entity_id=offer.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before={"status": OfferStatus.PENDING.value},
            after={"status": offer.status.value, "order_id": str(order.id)},
        )
        self.notifications.notify(
            offer.buyer_user_id,
            notification_type=NotificationType.OFFER_ACCEPTED,
            title=f"Offer accepted - order {order.order_number} created",
            body=(
                f"Your offer on lot {lot.lot_code} was accepted. "
                f"{order.quantity:,.0f} {normalise_unit(order.unit)} at "
                f"₹{order.agreed_price:,.0f}/{normalise_unit(order.unit)} "
                f"(total ₹{order.total_value:,.0f})."
            ),
            link="/orders",
            data={"order_id": str(order.id), "order_number": order.order_number},
        )
        return order

    def reject(self, offer_id: uuid.UUID, user: User, *, reason: str | None = None) -> Offer:
        offer = self.get_offer(offer_id)
        lot = self.lots.get_detailed(offer.lot_id)
        if lot is None:
            raise NotFoundError("The linked lot no longer exists.", code="LOT_NOT_FOUND")
        allowed = user.id == lot.seller_user_id or user.id == offer.buyer_user_id
        if not allowed and user.role.value != "ADMIN":
            raise PermissionDeniedError(
                "Only the seller or the buyer can respond to this offer.", code="OFFER_NOT_PARTY"
            )
        if offer.status is not OfferStatus.PENDING:
            raise InvalidStateTransitionError(
                f"This offer is already {offer.status.value.lower()}.", code="OFFER_NOT_PENDING"
            )
        if user.id == offer.buyer_user_id and user.id != lot.seller_user_id:
            offer.status = OfferStatus.WITHDRAWN
            action = "OFFER_WITHDRAWN"
        else:
            offer.status = OfferStatus.REJECTED
            action = "OFFER_REJECTED"
        offer.responded_at = datetime.now(UTC)
        offer.responded_by_user_id = user.id
        offer.decline_reason = reason
        if lot is not None:
            lot.active_offers_count = self.offers.pending_count_for_lot(lot.id)
            if lot.active_offers_count == 0 and lot.status is LotStatus.UNDER_OFFER:
                lot.status = LotStatus.PUBLISHED
        self.session.flush()
        self.audit.record(
            action=action,
            entity_type="offer",
            entity_id=offer.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before={"status": OfferStatus.PENDING.value},
            after={"status": offer.status.value},
            note=reason,
        )
        counterpart = offer.buyer_user_id if user.id == lot.seller_user_id else lot.seller_user_id
        self.notifications.notify(
            counterpart,
            notification_type=NotificationType.OFFER_REJECTED,
            title=f"Offer {offer.reference_code} was not accepted",
            body=reason or "Your offer was closed without acceptance.",
            link="/offers",
        )
        return self.get_offer(offer_id)

    def counter(self, offer_id: uuid.UUID, payload: OfferCounter, user: User) -> Offer:
        offer = self.get_offer(offer_id)
        lot = self.lots.get_detailed(offer.lot_id)
        if lot is None:
            raise NotFoundError("The linked lot no longer exists.", code="LOT_NOT_FOUND")
        if user.id != lot.seller_user_id:
            raise PermissionDeniedError(
                "Only the seller can send a counter offer on this lot.",
                code="OFFER_NOT_SELLER",
            )
        if offer.status is not OfferStatus.PENDING:
            raise InvalidStateTransitionError(
                "Only a pending offer can be countered.", code="OFFER_NOT_PENDING"
            )
        counter = Offer(
            lot_id=offer.lot_id,
            buyer_user_id=offer.buyer_user_id,
            demand_id=offer.demand_id,
            reference_code=offer_code(),
            offered_price=payload.offered_price,
            quantity=payload.quantity,
            unit=payload.unit,
            delivery_terms=payload.delivery_terms or offer.delivery_terms,
            payment_terms=payload.payment_terms or offer.payment_terms,
            payment_terms_days=(
                payload.payment_terms_days
                if payload.payment_terms_days is not None
                else offer.payment_terms_days
            ),
            valid_until=payload.valid_until
            or datetime.now(UTC) + timedelta(hours=DEFAULT_VALIDITY_HOURS),
            notes=payload.notes,
            status=OfferStatus.PENDING,
            parent_offer_id=offer.id,
            is_active=True,
        )
        offer.status = OfferStatus.COUNTERED
        offer.responded_at = datetime.now(UTC)
        offer.responded_by_user_id = user.id
        self.session.add(counter)
        self.session.flush()
        self.audit.record(
            action="OFFER_COUNTERED",
            entity_type="offer",
            entity_id=counter.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={
                "parent_offer": offer.reference_code,
                "counter_offer": counter.reference_code,
                "offered_price": counter.offered_price,
            },
        )
        self.notifications.notify(
            offer.buyer_user_id,
            notification_type=NotificationType.COUNTER_OFFER,
            title=f"Counter offer on {lot.lot_code}",
            body=(
                f"The seller countered at ₹{counter.offered_price:,.0f}/"
                f"{normalise_unit(counter.unit)} for {counter.quantity:,.0f} "
                f"{normalise_unit(counter.unit)}."
            ),
            link="/offers",
            data={"offer_id": str(counter.id), "lot_id": str(lot.id)},
        )
        return self.get_offer(counter.id)

    def withdraw(self, offer_id: uuid.UUID, user: User) -> Offer:
        return self.reject(offer_id, user, reason="Withdrawn by the buyer")

    def expire_due_offers(self) -> int:
        now = datetime.now(UTC)
        due = self.offers.find_all(
            filters={"status": OfferStatus.PENDING, "is_active": True}, limit=500
        )
        count = 0
        for offer in due:
            if offer.valid_until and offer.valid_until < now:
                offer.status = OfferStatus.EXPIRED
                offer.is_active = False
                offer.responded_at = now
                lot = self.lots.get(offer.lot_id)
                if lot is not None:
                    lot.active_offers_count = self.offers.pending_count_for_lot(lot.id)
                    if lot.status is LotStatus.UNDER_OFFER and lot.active_offers_count == 0:
                        lot.status = LotStatus.PUBLISHED
                self.notifications.notify(
                    offer.buyer_user_id,
                    notification_type=NotificationType.OFFER_EXPIRING,
                    title=f"Offer {offer.reference_code} expired",
                    body="The validity window for this offer has ended. You can place a new offer.",
                    link="/offers",
                )
                count += 1
        if count:
            self.session.flush()
        return count

    # ------------------------------------------------------------- queries
    def list_offers(
        self,
        *,
        user: User,
        role_view: str = "all",
        lot_id: uuid.UUID | None = None,
        status: list[OfferStatus] | None = None,
        term: str | None = None,
        sort: str = "-created_at",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Offer], int]:
        if role_view == "buyer":
            stmt = self.offers.for_buyer(user.id)
        elif role_view == "seller":
            stmt = self.offers.for_seller(user.id)
        elif user.role.value == "BUYER":
            stmt = self.offers.for_buyer(user.id)
        elif user.role.value in ("FARMER", "FPO"):
            stmt = self.offers.for_seller(user.id)
        elif user.role.value == "ADMIN":
            stmt = self.offers._with_refs()
        else:
            from app.models import Order as _Order

            stmt = (
                self.offers._with_refs()
                .join(_Order, _Order.offer_id == Offer.id)
                .where(_Order.buyer_user_id == user.id)
            )
        if lot_id:
            stmt = stmt.where(Offer.lot_id == lot_id)
        if status:
            stmt = stmt.where(Offer.status.in_(status))
        if term:
            from sqlalchemy import func, or_

            pattern = f"%{term.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Offer.reference_code).like(pattern),
                    func.lower(func.coalesce(Offer.notes, "")).like(pattern),
                    func.lower(FarmLot.title).like(pattern),
                )
            )
        for token in [sort, "created_at"]:
            descending = token.startswith("-")
            field = token.lstrip("-")
            column = getattr(Offer, field, None)
            if column is not None:
                stmt = stmt.order_by(column.desc() if descending else column.asc())
        return self.offers.paginate(stmt=stmt, page=page, page_size=page_size)

    def offers_for_lot(self, lot_id: uuid.UUID) -> list[Offer]:
        return self.offers.find_all(filters={"lot_id": lot_id}, order_by=["-created_at"], limit=100)

    def enrich(self, offer: Offer, viewer: User | None = None) -> dict[str, Any]:
        lot = offer.lot
        buyer = offer.buyer
        profile = getattr(buyer, "buyer_profile", None) if buyer else None
        can_respond = False
        if viewer is not None and offer.status is OfferStatus.PENDING:
            if lot is not None and viewer.id == lot.seller_user_id:
                can_respond = True
        return {
            "id": offer.id,
            "reference_code": offer.reference_code,
            "lot_id": offer.lot_id,
            "lot_code": lot.lot_code if lot else None,
            "lot_title": lot.title if lot else None,
            "commodity_id": lot.commodity_id if lot else None,
            "commodity_name": lot.commodity.name if lot and lot.commodity else None,
            "buyer_user_id": offer.buyer_user_id,
            "buyer_name": buyer.full_name if buyer else None,
            "buyer_organisation": profile.organisation_name if profile else None,
            "buyer_verified": bool(
                profile and profile.verification_status is VerificationStatus.VERIFIED
            ),
            "demand_id": offer.demand_id,
            "offered_price": offer.offered_price,
            "quantity": offer.quantity,
            "unit": offer.unit,
            "delivery_terms": offer.delivery_terms,
            "payment_terms": offer.payment_terms,
            "payment_terms_days": offer.payment_terms_days,
            "valid_until": offer.valid_until,
            "notes": offer.notes,
            "status": offer.status,
            "parent_offer_id": offer.parent_offer_id,
            "responded_at": offer.responded_at,
            "decline_reason": offer.decline_reason,
            "total_value": round(offer.offered_price * offer.quantity, 2),
            "created_at": offer.created_at,
            "is_buyer": bool(viewer and viewer.id == offer.buyer_user_id),
            "is_seller": bool(viewer and lot and viewer.id == lot.seller_user_id),
            "can_respond": can_respond,
        }

    def negotiation_history(self, offer_id: uuid.UUID) -> list[dict[str, Any]]:
        chain = self.offers.negotiation_chain(offer_id)
        return [
            {
                "id": str(item.id),
                "reference_code": item.reference_code,
                "offered_price": item.offered_price,
                "quantity": item.quantity,
                "unit": item.unit,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
                "is_counter": item.parent_offer_id is not None,
            }
            for item in chain
        ]
