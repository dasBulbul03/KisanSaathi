"""Payment tracking service.

KisanSaathi is a *market linkage* platform, not a payment gateway. It records
the payment obligation created by an order and tracks its settlement, but it
never moves money itself. A gateway can be plugged in by implementing
``PaymentGateway`` and setting ``PAYMENT_GATEWAY=enabled``.
"""

from __future__ import annotations

import abc
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import (
    NotificationType,
    OrderStatus,
    PaymentStatus,
    UserRole,
)
from app.core.exceptions import (
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.models import Order, Payment, Transaction, User
from app.repositories.operations import PaymentRepository
from app.repositories.trade import OrderRepository, TransactionRepository
from app.schemas.operations import PaymentUpdate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.units import normalise_unit

logger = get_logger(__name__)

PAYMENT_TRANSITIONS: dict[PaymentStatus, set[PaymentStatus]] = {
    PaymentStatus.PENDING: {PaymentStatus.PROCESSING, PaymentStatus.PAID, PaymentStatus.FAILED},
    PaymentStatus.PROCESSING: {PaymentStatus.PAID, PaymentStatus.FAILED},
    PaymentStatus.PAID: {PaymentStatus.DISPUTED},
    PaymentStatus.FAILED: {PaymentStatus.PROCESSING, PaymentStatus.PAID},
    PaymentStatus.DISPUTED: {PaymentStatus.PAID, PaymentStatus.PROCESSING},
}

STATUS_LABELS: dict[PaymentStatus, str] = {
    PaymentStatus.PENDING: "Pending",
    PaymentStatus.PROCESSING: "Processing",
    PaymentStatus.PAID: "Paid",
    PaymentStatus.FAILED: "Failed",
    PaymentStatus.DISPUTED: "Disputed",
}


class PaymentGateway(abc.ABC):
    """Optional integration seam for a real payment service provider."""

    name = "abstract"

    @abc.abstractmethod
    def initiate(self, payment: Payment) -> dict[str, Any]: ...

    @abc.abstractmethod
    def verify(self, payment: Payment) -> dict[str, Any]: ...


class ManualPaymentGateway(PaymentGateway):
    """Default: the payer records settlement themselves (offline NEFT/RTGS/etc)."""

    name = "manual"

    def initiate(self, payment: Payment) -> dict[str, Any]:
        return {
            "status": "manual",
            "message": "Record the UTR / reference number once the transfer is made.",
        }

    def verify(self, payment: Payment) -> dict[str, Any]:
        return {
            "status": payment.status.value,
            "reference_number": payment.reference_number,
        }


class PaymentService:
    def __init__(self, session: Session, gateway: PaymentGateway | None = None) -> None:
        self.session = session
        self.payments = PaymentRepository(Payment, session)
        self.orders = OrderRepository(Order, session)
        self.transactions = TransactionRepository(Transaction, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)
        self.gateway = gateway or ManualPaymentGateway()

    def get(self, payment_id: uuid.UUID) -> Payment:
        payment = self.payments.get(payment_id)
        if payment is None:
            raise NotFoundError("The payment record could not be found.", code="PAYMENT_NOT_FOUND")
        return payment

    def list_payments(
        self,
        *,
        user: User,
        as_payer: bool | None = None,
        status: list[PaymentStatus] | None = None,
        overdue_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Payment], int]:
        if user.role is UserRole.ADMIN:
            stmt = self.payments.search_query(status=status, overdue_only=overdue_only)
        elif user.role is UserRole.FARMER or user.role is UserRole.FPO:
            stmt = self.payments.search_query(
                user_id=user.id, as_payer=False, status=status, overdue_only=overdue_only
            )
        else:
            stmt = self.payments.search_query(
                user_id=user.id, as_payer=as_payer, status=status, overdue_only=overdue_only
            )
        return self.payments.paginate(stmt=stmt, page=page, page_size=page_size)

    def update_status(self, payment_id: uuid.UUID, payload: PaymentUpdate, user: User) -> Payment:
        payment = self.get(payment_id)
        allowed = {
            UserRole.ADMIN,
            UserRole.BUYER,
        }
        if user.role not in allowed and payment.payee_user_id != user.id:
            raise PermissionDeniedError(
                "Only the payer or an administrator can update this payment.",
                code="PAYMENT_UPDATE_FORBIDDEN",
            )
        if user.role is UserRole.BUYER and payment.payer_user_id != user.id:
            raise PermissionDeniedError(
                "Only the payer can record this settlement.", code="PAYMENT_UPDATE_FORBIDDEN"
            )
        if payload.status is not payment.status:
            permitted = PAYMENT_TRANSITIONS.get(payment.status, set())
            if payload.status not in permitted:
                raise InvalidStateTransitionError(
                    f"A {STATUS_LABELS[payment.status].lower()} payment cannot move to "
                    f"{STATUS_LABELS.get(payload.status, payload.status.value).lower()}.",
                    code="PAYMENT_INVALID_TRANSITION",
                )
        before = payment.status.value
        data = payload.model_dump(exclude_unset=True)
        new_status = data.pop("status")
        for key, value in data.items():
            if value is not None and hasattr(payment, key):
                setattr(payment, key, value)
        payment.status = new_status
        if new_status is PaymentStatus.PROCESSING and payment.initiated_at is None:
            payment.initiated_at = datetime.now(UTC)
        if new_status is PaymentStatus.PAID:
            payment.paid_at = payload.paid_at or datetime.now(UTC)
            payment.failure_reason = None
        if new_status is PaymentStatus.FAILED:
            payment.failure_reason = payload.failure_reason
        self.session.flush()

        order = self.orders.get(payment.order_id) if payment.order_id else None
        if order is not None:
            transaction = self.transactions.get(payment.transaction_id)
            if transaction is not None:
                target = {
                    PaymentStatus.PAID: OrderStatus.PAYMENT_COMPLETED,
                    PaymentStatus.PENDING: OrderStatus.PAYMENT_PENDING,
                    PaymentStatus.PROCESSING: OrderStatus.PAYMENT_PENDING,
                }.get(new_status)
                if target:
                    from app.services.order_service import OrderService

                    service = OrderService(self.session)
                    service.advance_through(order, target, user)
        self.audit.record(
            action="PAYMENT_UPDATED",
            entity_type="payment",
            entity_id=payment.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before={"status": before},
            after={"status": new_status.value, "reference_number": payment.reference_number},
        )
        reference = (
            payment.transaction.transaction_reference
            if payment.transaction
            else payment.transaction_id
        )
        self.notifications.notify(
            payment.payee_user_id,
            notification_type=NotificationType.PAYMENT_UPDATE,
            title=f"Payment {STATUS_LABELS[new_status]}",
            body=(
                f"₹{payment.amount:,.0f} for transaction {reference} "
                f"is now {new_status.value.lower()}."
            ),
            link="/payments",
        )
        return payment

    def summary_for(self, user: User) -> dict[str, Any]:
        as_payee = user.role in (UserRole.FARMER, UserRole.FPO)
        return self.payments.summary_for_user(user.id, as_payee=as_payee)

    def platform_summary(self) -> dict[str, Any]:
        return self.payments.platform_summary()

    def enrich(self, payment: Payment) -> dict[str, Any]:
        transaction = payment.transaction
        # Payment has an order_id but no ``order`` relationship, so it is
        # resolved explicitly; the repository keeps this off the N+1 path
        # because the transaction's order is eager loaded alongside it.
        order = transaction.order if transaction else None
        if order is None and payment.order_id:
            order = self.orders.get(payment.order_id)
        return {
            "id": payment.id,
            "transaction_id": payment.transaction_id,
            "transaction_reference": transaction.transaction_reference if transaction else None,
            "order_id": payment.order_id,
            "order_number": order.order_number if order else None,
            "payer_user_id": payment.payer_user_id,
            "payer_name": payment.payer.full_name if payment.payer else None,
            "payee_user_id": payment.payee_user_id,
            "payee_name": payment.payee.full_name if payment.payee else None,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "method": payment.method,
            "due_date": payment.due_date,
            "reference_number": payment.reference_number,
            "initiated_at": payment.initiated_at,
            "paid_at": payment.paid_at,
            "failure_reason": payment.failure_reason,
            "notes": payment.notes,
            "is_demo": payment.is_demo,
            "created_at": payment.created_at,
            "is_overdue": bool(
                payment.due_date
                and payment.due_date < date.today()
                and payment.status in (PaymentStatus.PENDING, PaymentStatus.PROCESSING)
            ),
            "amount_display": f"₹{payment.amount:,.0f}",
            "unit_hint": normalise_unit(order.unit) if order else None,
        }

    def due_soon(self, days: int = 7, *, user_id: uuid.UUID | None = None) -> list[Payment]:
        """Unsettled payments whose due date falls within the next ``days`` days.

        Scoped to a user when ``user_id`` is given, so the endpoint cannot leak
        the platform's whole receivables book to any authenticated caller.
        """
        stmt = self.payments.due_soon_query(days=days, user_id=user_id)
        return list(self.session.execute(stmt).unique().scalars().all())
