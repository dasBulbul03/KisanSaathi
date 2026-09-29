"""Order and transaction lifecycle.

Every transition is validated against an explicit state machine and written to
the audit log. AI components are never allowed to call these mutating methods -
see ``app/ai/prompts.py`` and ``docs/ai.md``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import (
    DemandStatus,
    LogisticsStatus,
    LotStatus,
    NotificationType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.core.exceptions import (
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.models import FarmLot, LogisticsRequest, Offer, Order, Payment, Transaction, User
from app.repositories.operations import LogisticsRepository, PaymentRepository
from app.repositories.trade import LotRepository, OfferRepository, OrderRepository
from app.schemas.trade import OrderStatusUpdate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.codes import order_number as new_order_number
from app.utils.codes import transaction_reference as new_transaction_reference
from app.utils.units import convert_quantity, normalise_unit

logger = get_logger(__name__)

#: Allowed forward transitions for the order state machine.
ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.OFFER_ACCEPTED: {OrderStatus.ORDER_CREATED, OrderStatus.CANCELLED},
    OrderStatus.ORDER_CREATED: {
        OrderStatus.LOGISTICS_ASSIGNED,
        OrderStatus.PICKUP_SCHEDULED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.CANCELLED,
    },
    OrderStatus.LOGISTICS_ASSIGNED: {
        OrderStatus.PICKUP_SCHEDULED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.CANCELLED,
    },
    OrderStatus.PICKUP_SCHEDULED: {
        OrderStatus.IN_TRANSIT,
        OrderStatus.DELIVERED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.IN_TRANSIT: {OrderStatus.DELIVERED, OrderStatus.CANCELLED},
    OrderStatus.DELIVERED: {OrderStatus.QUALITY_CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.QUALITY_CONFIRMED: {OrderStatus.PAYMENT_PENDING, OrderStatus.COMPLETED},
    OrderStatus.PAYMENT_PENDING: {OrderStatus.PAYMENT_COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.PAYMENT_COMPLETED: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}

#: Roles that may act on any order, not just ones they are party to.
PLATFORM_STAFF_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.ADMIN, UserRole.QUALITY_INSPECTOR, UserRole.LOGISTICS_PARTNER}
)

#: Which roles may drive which transition.
TRANSITION_ROLES: dict[OrderStatus, set[UserRole]] = {
    OrderStatus.OFFER_ACCEPTED: {UserRole.ADMIN},
    OrderStatus.ORDER_CREATED: {UserRole.ADMIN},
    OrderStatus.LOGISTICS_ASSIGNED: {UserRole.ADMIN, UserRole.LOGISTICS_PARTNER},
    OrderStatus.PICKUP_SCHEDULED: {
        UserRole.ADMIN,
        UserRole.LOGISTICS_PARTNER,
        UserRole.FARMER,
        UserRole.FPO,
    },
    OrderStatus.IN_TRANSIT: {UserRole.ADMIN, UserRole.LOGISTICS_PARTNER},
    OrderStatus.DELIVERED: {UserRole.ADMIN, UserRole.LOGISTICS_PARTNER, UserRole.BUYER},
    OrderStatus.QUALITY_CONFIRMED: {
        UserRole.ADMIN,
        UserRole.QUALITY_INSPECTOR,
        UserRole.BUYER,
    },
    OrderStatus.PAYMENT_PENDING: {UserRole.ADMIN, UserRole.BUYER},
    OrderStatus.PAYMENT_COMPLETED: {UserRole.ADMIN, UserRole.BUYER},
    OrderStatus.COMPLETED: {UserRole.ADMIN},
    OrderStatus.CANCELLED: {UserRole.ADMIN},
}

#: ``(current status, target status)`` pairs a buyer may drive on their own order
#: without being a logistics partner or inspector. Buying means being present at
#: delivery, so the buyer signs off on arrival and on the goods themselves.
BUYER_SELF_SERVICE_TRANSITIONS: frozenset[tuple[OrderStatus, OrderStatus]] = frozenset(
    {
        (OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED),
        (OrderStatus.DELIVERED, OrderStatus.QUALITY_CONFIRMED),
    }
)

STATUS_LABELS: dict[OrderStatus, str] = {
    OrderStatus.OFFER_ACCEPTED: "Offer accepted",
    OrderStatus.ORDER_CREATED: "Order created",
    OrderStatus.LOGISTICS_ASSIGNED: "Logistics assigned",
    OrderStatus.PICKUP_SCHEDULED: "Pickup scheduled",
    OrderStatus.IN_TRANSIT: "In transit",
    OrderStatus.DELIVERED: "Delivered",
    OrderStatus.QUALITY_CONFIRMED: "Quality confirmed",
    OrderStatus.PAYMENT_PENDING: "Payment pending",
    OrderStatus.PAYMENT_COMPLETED: "Payment completed",
    OrderStatus.COMPLETED: "Completed",
    OrderStatus.CANCELLED: "Cancelled",
}


class OrderService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.orders = OrderRepository(Order, session)
        self.offers = OfferRepository(Offer, session)
        self.lots = LotRepository(FarmLot, session)
        self.logistics = LogisticsRepository(LogisticsRequest, session)
        self.payments = PaymentRepository(Payment, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    # ------------------------------------------------------------- helpers
    def get_order(self, order_id: uuid.UUID) -> Order:
        order = self.orders.get_detailed(order_id)
        if order is None or order.is_deleted:
            raise NotFoundError("The requested order could not be found.", code="ORDER_NOT_FOUND")
        return order

    def assert_party(self, order: Order, user: User) -> None:
        """Access check: the two trading parties plus platform staff.

        Inspectors and logistics partners act on orders they are not parties to,
        so they are treated as staff here; ``can_transition`` still limits which
        state changes each role may perform.
        """
        if user.id in (order.buyer_user_id, order.seller_user_id):
            return
        if user.role in PLATFORM_STAFF_ROLES:
            return
        raise PermissionDeniedError("You do not have access to this order.", code="ORDER_FORBIDDEN")

    def can_transition(self, order: Order, target: OrderStatus, user: User) -> bool:
        if target not in ORDER_TRANSITIONS.get(order.status, set()):
            return False
        if user.role in TRANSITION_ROLES.get(target, set()):
            return True
        return (
            user.id == order.buyer_user_id
            and (order.status, target) in BUYER_SELF_SERVICE_TRANSITIONS
        )

    # ------------------------------------------------------------- create
    def create_from_offer(self, *, offer: Offer, lot: FarmLot, actor: User) -> Order:
        quantity = offer.quantity
        total_value = round(offer.offered_price * quantity, 2)
        pickup_date = lot.available_from or date.today()
        order = Order(
            order_number=new_order_number(),
            offer_id=offer.id,
            lot_id=lot.id,
            buyer_user_id=offer.buyer_user_id,
            seller_user_id=lot.seller_user_id,
            commodity_id=lot.commodity_id,
            quantity=quantity,
            unit=offer.unit,
            agreed_price=offer.offered_price,
            total_value=total_value,
            quality_grade=lot.quality_grade,
            status=OrderStatus.ORDER_CREATED,
            pickup_location=", ".join(p for p in [lot.village, lot.taluka, lot.district] if p)
            or "Pickup location as per lot",
            pickup_district=lot.district,
            delivery_location=(
                offer.demand.delivery_location
                if offer.demand
                else (offer.delivery_terms or "As per agreement")
            ),
            delivery_district=offer.demand.district if offer.demand else None,
            pickup_date=pickup_date,
            delivery_date=pickup_date + timedelta(days=2),
            payment_terms_days=offer.payment_terms_days,
            status_history=[
                {
                    "status": OrderStatus.OFFER_ACCEPTED.value,
                    "at": datetime.now(UTC).isoformat(),
                    "by": str(actor.id),
                    "note": f"Offer {offer.reference_code} accepted",
                },
                {
                    "status": OrderStatus.ORDER_CREATED.value,
                    "at": datetime.now(UTC).isoformat(),
                    "by": str(actor.id),
                    "note": "Order and ledger entry created",
                },
            ],
        )
        self.session.add(order)
        self.session.flush()

        transaction = Transaction(
            transaction_reference=new_transaction_reference(),
            order_id=order.id,
            seller_user_id=order.seller_user_id,
            buyer_user_id=order.buyer_user_id,
            commodity_id=order.commodity_id,
            quantity=order.quantity,
            unit=order.unit,
            unit_price=order.agreed_price,
            total_amount=order.total_value,
            platform_fee=0.0,
            status=order.status,
            district=lot.district,
            initiated_at=datetime.now(UTC),
        )
        self.session.add(transaction)
        self.session.flush()

        due_date = (order.pickup_date or date.today()) + timedelta(days=order.payment_terms_days)
        payment = Payment(
            transaction_id=transaction.id,
            order_id=order.id,
            payer_user_id=order.buyer_user_id,
            payee_user_id=order.seller_user_id,
            amount=order.total_value,
            status=PaymentStatus.PENDING,
            method=PaymentMethod.BANK_TRANSFER,
            due_date=due_date,
            notes=(
                "Payment obligation created on order confirmation. No money is moved by the "
                "platform; the payer records settlement manually or via a configured gateway."
            ),
        )
        self.session.add(payment)

        # Reserve the quantity and move the lot to SOLD.
        lot.available_quantity = max(
            0.0, lot.available_quantity - convert_quantity(quantity, offer.unit, lot.unit)
        )
        lot.status = LotStatus.SOLD
        if offer.demand:
            offer.demand.fulfilled_quantity = min(
                offer.demand.required_quantity,
                offer.demand.fulfilled_quantity + quantity,
            )
            if offer.demand.fulfilled_quantity >= offer.demand.required_quantity:
                offer.demand.status = DemandStatus.FULFILLED
        self.session.flush()
        self.audit.record(
            action="ORDER_CREATED",
            entity_type="order",
            entity_id=order.id,
            actor_user_id=actor.id,
            actor_role=actor.role,
            after={
                "order_number": order.order_number,
                "total_value": order.total_value,
                "transaction_reference": transaction.transaction_reference,
            },
        )
        logger.info("order.created", order=str(order.order_number), total=order.total_value)
        return order

    def advance_through(self, order: Order, target: OrderStatus, user: User) -> bool:
        """Walk an order to ``target``, filling in intermediate payment states.

        A recorded settlement should not be blocked just because the order sat
        in ``QUALITY_CONFIRMED``; it moves through ``PAYMENT_PENDING`` first.
        Returns ``True`` when the order ends in ``target``.
        """
        from app.schemas.trade import OrderStatusUpdate

        if order.status is target:
            return True
        chain: list[OrderStatus] = [target]
        if (
            target is OrderStatus.PAYMENT_COMPLETED
            and order.status is OrderStatus.QUALITY_CONFIRMED
        ):
            chain = [OrderStatus.PAYMENT_PENDING, OrderStatus.PAYMENT_COMPLETED]
        elif target is OrderStatus.COMPLETED and order.status in (
            OrderStatus.QUALITY_CONFIRMED,
            OrderStatus.PAYMENT_PENDING,
            OrderStatus.PAYMENT_COMPLETED,
        ):
            chain = [
                OrderStatus.PAYMENT_PENDING,
                OrderStatus.PAYMENT_COMPLETED,
                OrderStatus.COMPLETED,
            ]
        for step in chain:
            if order.status is step:
                continue
            if not self.can_transition(order, step, user):
                return False
            self.update_status(
                order.id,
                OrderStatusUpdate(status=step, note="Automatic settlement advance"),
                user,
            )
        return order.status is target

    # ---------------------------------------------------------- transitions
    def update_status(self, order_id: uuid.UUID, payload: OrderStatusUpdate, user: User) -> Order:
        order = self.get_order(order_id)
        self.assert_party(order, user)
        target = payload.status
        if not self.can_transition(order, target, user):
            if target not in ORDER_TRANSITIONS.get(order.status, set()):
                raise InvalidStateTransitionError(
                    f"An order in {STATUS_LABELS.get(order.status, order.status.value)} "
                    f"cannot move to {STATUS_LABELS.get(target, target.value)}.",
                    code="INVALID_TRANSITION",
                )
            raise PermissionDeniedError(
                f"Your role cannot perform the {STATUS_LABELS.get(target, target.value).lower()} "
                "step for this order.",
                code="TRANSITION_NOT_ALLOWED",
            )

        previous = order.status
        order.status = target
        if payload.pickup_date:
            order.pickup_date = payload.pickup_date
        if payload.delivery_date:
            order.delivery_date = payload.delivery_date
        if target is OrderStatus.CANCELLED:
            order.cancelled_reason = payload.reason or payload.note
        history = list(order.status_history or [])
        history.append(
            {
                "status": target.value,
                "at": datetime.now(UTC).isoformat(),
                "by": str(user.id),
                "by_name": user.full_name,
                "role": user.role.value,
                "note": payload.note or payload.reason,
            }
        )
        order.status_history = history
        if order.transaction:
            order.transaction.status = target
        if target is OrderStatus.COMPLETED and order.transaction:
            order.transaction.completed_at = datetime.now(UTC)
        if target in (OrderStatus.PAYMENT_PENDING, OrderStatus.PAYMENT_COMPLETED):
            payment = self.payments.find_one_by(transaction_id=order.transaction.id)
            if payment and target is OrderStatus.PAYMENT_COMPLETED:
                payment.status = PaymentStatus.PAID
                payment.paid_at = datetime.now(UTC)
                payment.initiated_at = payment.initiated_at or datetime.now(UTC)
                payment.reference_number = payment.reference_number or (
                    f"PAY-{payment.id.hex[:10].upper()}"
                )
        if target is OrderStatus.DELIVERED and order.lot:
            order.lot.status = LotStatus.COMPLETED
        if target is OrderStatus.IN_TRANSIT and order.lot:
            order.lot.status = LotStatus.IN_TRANSIT
        self.session.flush()

        logistics = order.logistics_request
        if logistics is not None:
            self._sync_logistics_status(order, logistics, target)

        self.audit.record(
            action=f"ORDER_{target.value}",
            entity_type="order",
            entity_id=order.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before={"status": previous.value},
            after={"status": target.value},
            note=payload.note or payload.reason,
        )
        recipients = {order.buyer_user_id, order.seller_user_id}
        if logistics and logistics.provider_user_id:
            recipients.add(logistics.provider_user_id)
        self.notifications.notify_many(
            list(recipients),
            notification_type=NotificationType.ORDER_UPDATE,
            title=f"Order {order.order_number}: {STATUS_LABELS.get(target, target.value)}",
            body=(
                f"{STATUS_LABELS.get(target, target.value)} for {order.quantity:,.0f} "
                f"{normalise_unit(order.unit)} of "
                f"{order.commodity.name if order.commodity else 'produce'}."
            ),
            link="/orders",
            data={"order_id": str(order.id), "order_number": order.order_number},
        )
        return self.get_order(order_id)

    @staticmethod
    def _sync_logistics_status(
        order: Order, logistics: LogisticsRequest, target: OrderStatus
    ) -> None:
        mapping = {
            OrderStatus.LOGISTICS_ASSIGNED: LogisticsStatus.ASSIGNED,
            OrderStatus.PICKUP_SCHEDULED: LogisticsStatus.PICKUP_SCHEDULED,
            OrderStatus.IN_TRANSIT: LogisticsStatus.IN_TRANSIT,
            OrderStatus.DELIVERED: LogisticsStatus.DELIVERED,
        }
        new_status = mapping.get(target)
        if new_status is None or logistics.status is new_status:
            return
        history = list(logistics.status_history or [])
        history.append(
            {
                "status": new_status.value,
                "at": datetime.now(UTC).isoformat(),
                "source": f"order:{order.order_number}",
            }
        )
        logistics.status_history = history
        logistics.status = new_status
        if new_status is LogisticsStatus.PICKUP_SCHEDULED:
            logistics.pickup_date = order.pickup_date or logistics.pickup_date
        if new_status is LogisticsStatus.DELIVERED:
            logistics.delivery_actual_at = datetime.now(UTC)
        if new_status is LogisticsStatus.IN_TRANSIT:
            logistics.pickup_actual_at = logistics.pickup_actual_at or datetime.now(UTC)

    # ------------------------------------------------------------ queries
    def list_orders(
        self,
        *,
        user: User | None = None,
        user_id: uuid.UUID | None = None,
        user_role: UserRole | None = None,
        status: list[OrderStatus] | None = None,
        commodity_id: uuid.UUID | None = None,
        district: str | None = None,
        sort: str = "-created_at",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Order], int]:
        stmt = self.orders.search_query(
            user_id=user_id or (user.id if user else None),
            user_role=user_role or (user.role if user else None),
            status=status,
            commodity_id=commodity_id,
            district=district,
        )
        for token in [sort, "created_at"]:
            descending = token.startswith("-")
            field = token.lstrip("-")
            column = getattr(Order, field, None)
            if column is not None:
                stmt = stmt.order_by(column.desc() if descending else column.asc())
        return self.orders.paginate(stmt=stmt, page=page, page_size=page_size)

    def pipeline(
        self, user_id: uuid.UUID | None = None, *, user_role: UserRole | None = None
    ) -> list[dict[str, Any]]:
        """Status funnel, either platform-wide or scoped to one user.

        ``user_role`` matters: without it a buyer's pipeline resolves down the
        seller branch and comes back empty, so callers that know the caller must
        pass it.
        """
        if user_id:
            buckets: dict[OrderStatus, dict[str, Any]] = {
                status: {"status": status.value, "count": 0, "value": 0.0} for status in OrderStatus
            }
            for status, count, value in self.orders.pipeline_counts_for_user(user_id, user_role):
                buckets[status] = {"status": status.value, "count": count, "value": value}
            return [buckets[s] for s in OrderStatus]
        return [
            {"status": status.value, "count": count, "value": value}
            for status, count, value in self.orders.pipeline_counts()
        ]

    def enrich(self, order: Order, viewer: User | None = None) -> dict[str, Any]:
        logistics = order.logistics_request
        payment = None
        if order.transaction:
            payment = order.transaction.payments[0] if order.transaction.payments else None
        buyer = order.buyer
        seller = order.seller
        buyer_org = getattr(buyer, "buyer_profile", None) if buyer else None
        seller_fpo = getattr(seller, "fpo_profile", None) if seller else None
        can_update = bool(
            viewer is not None
            and any(
                self.can_transition(order, target, viewer)
                for target in ORDER_TRANSITIONS.get(order.status, set())
            )
        )
        return {
            "id": order.id,
            "order_number": order.order_number,
            "offer_id": order.offer_id,
            "lot_id": order.lot_id,
            "lot_code": order.lot.lot_code if order.lot else None,
            "buyer_user_id": order.buyer_user_id,
            "buyer_name": buyer.full_name if buyer else None,
            "buyer_organisation": buyer_org.organisation_name if buyer_org else None,
            "seller_user_id": order.seller_user_id,
            "seller_name": seller.full_name if seller else None,
            "seller_organisation": seller_fpo.organisation_name if seller_fpo else None,
            "commodity_id": order.commodity_id,
            "commodity_name": order.commodity.name if order.commodity else None,
            "quantity": order.quantity,
            "unit": order.unit,
            "agreed_price": order.agreed_price,
            "total_value": order.total_value,
            "quality_grade": order.quality_grade,
            "status": order.status,
            "pickup_location": order.pickup_location,
            "pickup_district": order.pickup_district,
            "delivery_location": order.delivery_location,
            "delivery_district": order.delivery_district,
            "pickup_date": order.pickup_date,
            "delivery_date": order.delivery_date,
            "payment_terms_days": order.payment_terms_days,
            "status_history": order.status_history or [],
            "cancelled_reason": order.cancelled_reason,
            "logistics_status": logistics.status.value if logistics else None,
            "logistics_reference": logistics.reference_code if logistics else None,
            "payment_status": payment.status.value if payment else None,
            "payment_due_date": payment.due_date if payment else None,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "can_update_status": can_update,
        }

    def allowed_transitions(self, order: Order, user: User) -> list[OrderStatus]:
        return [
            target
            for target in ORDER_TRANSITIONS.get(order.status, set())
            if self.can_transition(order, target, user)
        ]


__all__ = [
    "ORDER_TRANSITIONS",
    "STATUS_LABELS",
    "TRANSITION_ROLES",
    "OrderService",
]
