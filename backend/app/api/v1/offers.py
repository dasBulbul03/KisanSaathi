"""Buyer offer and negotiation endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentBuyer,
    CurrentSeller,
    CurrentUser,
    DbSession,
    Pagination,
    require_permissions,
)
from app.core.enums import OfferStatus
from app.core.rbac import OFFER_CREATE
from app.models import User
from app.schemas.common import Page
from app.schemas.trade import (
    OfferCounter,
    OfferCreate,
    OfferOut,
    OfferReject,
    OrderOut,
)
from app.services.offer_service import OfferService
from app.services.order_service import OrderService

router = APIRouter(prefix="/offers", tags=["offers"])

OfferCreator = Annotated[User, Depends(require_permissions(OFFER_CREATE))]

#: Frontend vocabulary for the role-aware list view.
ROLE_VIEW_MAP = {"incoming": "seller", "outgoing": "buyer"}


def _offer_out(service: OfferService, offer: object, viewer: User | None = None) -> OfferOut:
    """Serialise an offer with buyer/seller context relative to the viewer."""
    return OfferOut.model_validate(service.enrich(offer, viewer=viewer))


def _order_out(service: OrderService, order: object, viewer: User | None = None) -> OrderOut:
    """Serialise an order from the enrich dict.

    The enrich payload also carries ``can_update_status``, which is not part of
    the OrderOut contract and is dropped here; the frontend drives action
    buttons from ``allowed-transitions`` instead.
    """
    data = service.enrich(order, viewer=viewer)
    data.pop("can_update_status", None)
    return OrderOut.model_validate(data)


@router.post(
    "/preflight",
    response_model=dict[str, Any],
    summary="Validate an offer before submitting",
)
def preflight_offer(payload: OfferCreate, session: DbSession, user: OfferCreator) -> dict[str, Any]:
    """Run non-mutating validation and return lot facts plus any warnings.

    Nothing is persisted; the frontend calls this to warn the buyer before
    they commit to a real offer.
    """
    return OfferService(session).preflight_offer(payload, user)


@router.post(
    "",
    response_model=OfferOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an offer",
)
def create_offer(payload: OfferCreate, session: DbSession, user: OfferCreator) -> OfferOut:
    """Place a pending buyer offer on a published lot."""
    service = OfferService(session)
    offer = service.create_offer(payload, user)
    session.commit()
    return _offer_out(service, offer, viewer=user)


@router.get("", response_model=Page[OfferOut], summary="List offers")
def list_offers(
    session: DbSession,
    params: Pagination,
    user: CurrentUser,
    role_view: Literal["all", "incoming", "outgoing"] = Query(
        "all", description="'incoming' = offers on my lots, 'outgoing' = offers I made"
    ),
    lot_id: uuid.UUID | None = Query(None, description="Restrict to a single lot"),
    status_list: list[OfferStatus] | None = Query(
        None, alias="status", description="Offer statuses"
    ),
    term: str | None = Query(None, description="Search reference, notes or lot title"),
    sort: str = "-created_at",
) -> Page[OfferOut]:
    """List the offers relevant to the caller.

    Defaults to a role-aware mix: buyers see their outgoing offers, sellers see
    offers on their lots, admins see everything. ``role_view`` overrides this.
    """
    service = OfferService(session)
    items, total = service.list_offers(
        user=user,
        role_view=ROLE_VIEW_MAP.get(role_view, "all"),
        lot_id=lot_id,
        status=status_list,
        term=term,
        sort=sort,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[OfferOut].build(
        [_offer_out(service, offer, viewer=user) for offer in items], total, params
    )


@router.get("/lot/{lot_id}", response_model=list[OfferOut], summary="Offers on a lot")
def offers_for_lot(lot_id: uuid.UUID, session: DbSession, user: CurrentUser) -> list[OfferOut]:
    """All offers placed on one lot, newest first."""
    service = OfferService(session)
    return [_offer_out(service, offer, viewer=user) for offer in service.offers_for_lot(lot_id)]


@router.get("/{offer_id}", response_model=OfferOut, summary="Offer detail")
def get_offer(offer_id: uuid.UUID, session: DbSession, user: CurrentUser) -> OfferOut:
    """Return a single offer with buyer and lot context."""
    service = OfferService(session)
    return _offer_out(service, service.get_offer(offer_id), viewer=user)


@router.post("/{offer_id}/accept", response_model=OrderOut, summary="Accept an offer")
def accept_offer(offer_id: uuid.UUID, session: DbSession, user: CurrentSeller) -> OrderOut:
    """Accept a pending offer and create the resulting order.

    This is the pivotal "offer accepted -> order created" transition: sibling
    pending offers for the lot are rejected, the lot reserves its quantity and
    moves to SOLD, and a ledger transaction plus payment obligation is created.
    """
    service = OfferService(session)
    order = service.accept(offer_id, user)
    session.commit()
    return _order_out(OrderService(session), order, viewer=user)


@router.post("/{offer_id}/reject", response_model=OfferOut, summary="Reject an offer")
def reject_offer(
    offer_id: uuid.UUID,
    payload: OfferReject,
    session: DbSession,
    user: CurrentSeller,
) -> OfferOut:
    """Close a pending offer; the optional reason is shown to the buyer."""
    service = OfferService(session)
    offer = service.reject(offer_id, user, reason=payload.reason)
    session.commit()
    return _offer_out(service, offer, viewer=user)


@router.post("/{offer_id}/counter", response_model=OfferOut, summary="Counter an offer")
def counter_offer(
    offer_id: uuid.UUID,
    payload: OfferCounter,
    session: DbSession,
    user: CurrentUser,
) -> OfferOut:
    """Reply to a pending offer with a counter offer; the original is marked COUNTERED."""
    service = OfferService(session)
    offer = service.counter(offer_id, payload, user)
    session.commit()
    return _offer_out(service, offer, viewer=user)


@router.post("/{offer_id}/withdraw", response_model=OfferOut, summary="Withdraw an offer")
def withdraw_offer(offer_id: uuid.UUID, session: DbSession, user: CurrentBuyer) -> OfferOut:
    """The buyer retracts their own pending offer."""
    service = OfferService(session)
    offer = service.withdraw(offer_id, user)
    session.commit()
    return _offer_out(service, offer, viewer=user)


@router.get(
    "/{offer_id}/history",
    response_model=list[dict[str, Any]],
    summary="Offer negotiation history",
)
def offer_history(
    offer_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> list[dict[str, Any]]:
    """The offer and every counter threaded beneath it, oldest first."""
    return OfferService(session).negotiation_history(offer_id)


__all__ = ["router"]
