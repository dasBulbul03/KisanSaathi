"""Payment obligation tracking endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, Pagination, require_permissions
from app.core.enums import PaymentStatus, UserRole
from app.core.exceptions import NotFoundError
from app.core.rbac import ANALYTICS_READ, PAYMENT_READ, PAYMENT_UPDATE
from app.models import Payment, User
from app.schemas.common import Page
from app.schemas.operations import PaymentOut, PaymentUpdate
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])

PaymentReader = Annotated[User, Depends(require_permissions(PAYMENT_READ))]
PaymentAnalyst = Annotated[User, Depends(require_permissions(ANALYTICS_READ))]
PaymentUpdater = Annotated[User, Depends(require_permissions(PAYMENT_UPDATE))]


def _is_party(payment: Payment, user: User) -> bool:
    """Whether *user* may see this payment.

    ``PaymentService.get`` and ``due_soon`` apply no ownership filter, so the
    payer/payee rule is enforced here; administrators see the whole ledger.
    """
    return user.role is UserRole.ADMIN or user.id in (
        payment.payer_user_id,
        payment.payee_user_id,
    )


def _payment_out(service: PaymentService, payment: Payment) -> PaymentOut:
    """Serialise a payment with counterparty, order and settlement context.

    The enrich payload also carries ``is_overdue``, ``amount_display`` and
    ``unit_hint``, which are outside the PaymentOut contract and dropped here.
    """
    return PaymentOut.model_validate(service.enrich(payment))


@router.get("", response_model=Page[PaymentOut], summary="List payments")
def list_payments(
    session: DbSession,
    params: Pagination,
    user: PaymentReader,
    as_payer: bool | None = Query(
        None, description="true = what I owe, false = what is owed to me"
    ),
    status_list: list[PaymentStatus] | None = Query(
        None, alias="status", description="Restrict to these payment statuses"
    ),
    overdue_only: bool = Query(False, description="Only unpaid payments past their due date"),
) -> Page[PaymentOut]:
    """Payments the caller is a party to, soonest due date first.

    ``as_payer`` only applies to buyers: sellers are always shown the money owed
    *to* them. Administrators see the whole ledger.
    """
    service = PaymentService(session)
    items, total = service.list_payments(
        user=user,
        as_payer=as_payer,
        status=status_list,
        overdue_only=overdue_only,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[PaymentOut].build(
        [_payment_out(service, payment) for payment in items], total, params
    )


@router.get("/summary", response_model=dict[str, Any], summary="Payment summary for the caller")
def payment_summary(session: DbSession, user: CurrentUser) -> dict[str, Any]:
    """Expected, paid and overdue totals plus a per-status breakdown.

    Sellers are always summarised as payees and buyers as payers, so the same
    call means "what customers owe me" for one side and "what I owe" for the other.
    """
    return PaymentService(session).summary_for(user)


@router.get(
    "/summary/platform",
    response_model=dict[str, Any],
    summary="Platform-wide payment totals",
)
def platform_payment_summary(session: DbSession, user: PaymentAnalyst) -> dict[str, Any]:
    """Whole-platform settlement totals - administrators only."""
    return PaymentService(session).platform_summary()


@router.get("/due-soon", response_model=list[PaymentOut], summary="Payments due soon")
def payments_due_soon(
    session: DbSession,
    user: PaymentReader,
    days: int = Query(7, ge=1, le=90, description="How far ahead to look"),
) -> list[PaymentOut]:
    """Unsettled obligations the caller is a party to, nearest due date first.

    ``days`` widens the window the service scans; the query itself is scoped to
    the caller so the list can only ever contain their own payments.
    """
    service = PaymentService(session)
    return [
        _payment_out(service, payment) for payment in service.due_soon(days=days, user_id=user.id)
    ]


@router.get("/{payment_id}", response_model=PaymentOut, summary="Payment detail")
def get_payment(payment_id: uuid.UUID, session: DbSession, user: CurrentUser) -> PaymentOut:
    """Return one payment with its order, transaction and counterparty context.

    A payment the caller is not a party to is reported as missing so ids cannot
    be probed.
    """
    service = PaymentService(session)
    payment = service.get(payment_id)
    if not _is_party(payment, user):
        raise NotFoundError("The payment record could not be found.", code="PAYMENT_NOT_FOUND")
    return _payment_out(service, payment)


@router.patch(
    "/{payment_id}/status",
    response_model=PaymentOut,
    summary="Record a payment status change",
)
def update_payment_status(
    payment_id: uuid.UUID,
    payload: PaymentUpdate,
    session: DbSession,
    user: PaymentUpdater,
) -> PaymentOut:
    """Move a payment along the settlement state machine.

    The platform never moves money: the payer records an offline transfer here,
    and the service rejects transitions the current status does not allow.
    """
    service = PaymentService(session)
    payment = service.update_status(payment_id, payload, user)
    session.commit()
    return _payment_out(service, payment)


__all__ = ["router"]
