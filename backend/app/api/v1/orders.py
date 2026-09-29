"""Order and transaction endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, Pagination, require_permissions
from app.core.enums import OrderStatus, PaymentStatus, UserRole
from app.core.rbac import ORDER_UPDATE_STATUS
from app.models import Order, User
from app.schemas.common import Page
from app.schemas.operations import LogisticsOut
from app.schemas.trade import OrderOut, OrderStatusUpdate, TransactionOut
from app.services.logistics_service import LogisticsService
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])

OrderStatusActor = Annotated[User, Depends(require_permissions(ORDER_UPDATE_STATUS))]


def _order_out(service: OrderService, order: object, viewer: User | None = None) -> OrderOut:
    """Serialise an order from the enrich dict.

    The enrich payload also carries ``can_update_status``, which is not part of
    the OrderOut contract and is dropped here; the frontend drives action
    buttons from ``allowed-transitions`` instead.
    """
    data = service.enrich(order, viewer=viewer)
    data.pop("can_update_status", None)
    return OrderOut.model_validate(data)


def _transaction_out(order: Order) -> TransactionOut:
    """Serialise the ledger entry for an order with counterparty context."""
    transaction = order.transaction
    payment = transaction.payments[0] if transaction.payments else None
    return TransactionOut(
        id=transaction.id,
        transaction_reference=transaction.transaction_reference,
        order_id=transaction.order_id,
        order_number=order.order_number,
        seller_user_id=transaction.seller_user_id,
        seller_name=order.seller.full_name if order.seller else None,
        buyer_user_id=transaction.buyer_user_id,
        buyer_name=order.buyer.full_name if order.buyer else None,
        commodity_id=transaction.commodity_id,
        commodity_name=order.commodity.name if order.commodity else None,
        quantity=transaction.quantity,
        unit=transaction.unit,
        unit_price=transaction.unit_price,
        total_amount=transaction.total_amount,
        platform_fee=transaction.platform_fee,
        status=transaction.status,
        district=transaction.district,
        initiated_at=transaction.initiated_at,
        completed_at=transaction.completed_at,
        payment_status=payment.status.value if payment else None,
        amount_paid=payment.amount if payment and payment.status is PaymentStatus.PAID else 0.0,
    )


@router.get("", response_model=Page[OrderOut], summary="List orders")
def list_orders(
    session: DbSession,
    params: Pagination,
    user: CurrentUser,
    user_id: uuid.UUID | None = Query(None, description="ADMIN only: scope results to one user"),
    status_list: list[OrderStatus] | None = Query(
        None, alias="status", description="Order statuses"
    ),
    commodity_id: uuid.UUID | None = Query(None, description="Filter by commodity"),
    district: str | None = Query(None, description="Pickup or delivery district"),
    sort: str = "-created_at",
) -> Page[OrderOut]:
    """List the orders the caller can see, newest first.

    Non-admins always see their own orders. An ADMIN may pass ``user_id`` to
    inspect one user's orders; without it the full platform list is returned.
    """
    service = OrderService(session)
    if user.role is UserRole.ADMIN:
        items, total = service.list_orders(
            user_id=user_id,
            status=status_list,
            commodity_id=commodity_id,
            district=district,
            sort=sort,
            page=params.page,
            page_size=params.page_size,
        )
    else:
        items, total = service.list_orders(
            user=user,
            status=status_list,
            commodity_id=commodity_id,
            district=district,
            sort=sort,
            page=params.page,
            page_size=params.page_size,
        )
    return Page[OrderOut].build(
        [_order_out(service, order, viewer=user) for order in items], total, params
    )


@router.get("/pipeline", response_model=list[dict[str, Any]], summary="Order pipeline counts")
def order_pipeline(
    session: DbSession,
    user: CurrentUser,
    user_id: uuid.UUID | None = Query(None, description="ADMIN only: scope pipeline to one user"),
) -> list[dict[str, Any]]:
    """Counts and total value per order status.

    Admins see the platform-wide pipeline; other roles get one scoped to their
    own orders.
    """
    if user.role is UserRole.ADMIN:
        return OrderService(session).pipeline(user_id=user_id)
    return OrderService(session).pipeline(user_id=user.id, user_role=user.role)


@router.get("/{order_id}", response_model=OrderOut, summary="Order detail")
def get_order(order_id: uuid.UUID, session: DbSession, user: CurrentUser) -> OrderOut:
    """Return a single order with logistics, payment and status history context.

    Visibility is a party check, not a role check: an order carries the other
    party's name, contact details and negotiated price, so a seller must not be
    able to read a stranger's order just by guessing the id.
    """
    service = OrderService(session)
    order = service.get_order(order_id)
    service.assert_party(order, user)
    return _order_out(service, order, viewer=user)


@router.post("/{order_id}/status", response_model=OrderOut, summary="Advance an order status")
def update_order_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    session: DbSession,
    user: OrderStatusActor,
) -> OrderOut:
    """Move the order to the target status.

    The transition is validated against the order state machine and the actor's
    role; invalid or unauthorised moves are rejected.
    """
    service = OrderService(session)
    order = service.update_status(order_id, payload, user)
    session.commit()
    return _order_out(service, order, viewer=user)


@router.get(
    "/{order_id}/allowed-transitions",
    response_model=list[OrderStatus],
    summary="Statuses the caller may advance to",
)
def allowed_transitions(
    order_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> list[OrderStatus]:
    """The next statuses this caller may move the order to - drives action buttons."""
    service = OrderService(session)
    return service.allowed_transitions(service.get_order(order_id), user)


@router.get(
    "/{order_id}/transactions",
    response_model=list[TransactionOut],
    summary="Ledger transactions for an order",
)
def order_transactions(
    order_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> list[TransactionOut]:
    """The ledger entry mirroring this order - one transaction per order."""
    order = OrderService(session).get_order(order_id)
    return [_transaction_out(order)] if order.transaction else []


@router.get(
    "/{order_id}/logistics",
    response_model=dict[str, Any],
    summary="Logistics job for an order",
)
def order_logistics(order_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    """The logistics job arranged for this order, or an empty result when none exists."""
    service = LogisticsService(session)
    request = service.get_for_order(order_id)
    if request is None:
        return {"order_id": order_id, "logistics": None}
    return {
        "order_id": order_id,
        "logistics": LogisticsOut.model_validate(service.enrich(request)),
    }


__all__ = ["router"]
