"""Transport quoting, request and job tracking endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, Pagination, require_permissions
from app.core.enums import LogisticsStatus
from app.core.rbac import (
    LOGISTICS_ASSIGN,
    LOGISTICS_READ,
    LOGISTICS_REQUEST,
    LOGISTICS_UPDATE,
)
from app.models import User
from app.schemas.common import Page
from app.schemas.operations import (
    LogisticsCreate,
    LogisticsOut,
    LogisticsQuoteOption,
    LogisticsQuoteRequest,
    LogisticsUpdate,
)
from app.services.logistics_service import LogisticsService

router = APIRouter(prefix="/logistics", tags=["logistics"])

LogisticsReader = Annotated[User, Depends(require_permissions(LOGISTICS_READ))]
LogisticsRequester = Annotated[User, Depends(require_permissions(LOGISTICS_REQUEST))]
LogisticsAssigner = Annotated[User, Depends(require_permissions(LOGISTICS_ASSIGN))]
LogisticsUpdater = Annotated[User, Depends(require_permissions(LOGISTICS_UPDATE))]

#: The public ``assigned`` view is the service's ``provider`` view.
ROLE_VIEWS: dict[str, str] = {"all": "all", "mine": "mine", "assigned": "provider"}


class AssignRequest(BaseModel):
    """Accept a pending job on behalf of a transport account."""

    provider_user_id: uuid.UUID = Field(description="Transporter account taking the job")


def _logistics_out(service: LogisticsService, request: object) -> LogisticsOut:
    """Serialise a transport job with its order and transporter context."""
    return LogisticsOut.model_validate(service.enrich(request))


@router.post(
    "/quotes",
    response_model=list[LogisticsQuoteOption],
    summary="Price a transport lane",
)
def quote_transport(
    payload: LogisticsQuoteRequest, session: DbSession, user: LogisticsReader
) -> list[LogisticsQuoteOption]:
    """Indicative cost options for a lane, cheapest first.

    Options come from the rate cards and are not a booked transporter; each one
    carries ``is_demo`` so the client can label the estimate honestly.
    """
    service = LogisticsService(session)
    return [
        LogisticsQuoteOption(
            provider_name=option.provider_name,
            vehicle_type=option.vehicle_type,
            distance_km=option.distance_km,
            estimated_cost=option.estimated_cost,
            transit_days=option.transit_days,
            rating=option.rating,
            is_demo=option.is_demo,
            note=option.note,
        )
        for option in service.quote_options(
            origin_district=payload.origin_district,
            destination_district=payload.destination_district,
            quantity=payload.quantity,
            unit=payload.unit,
            cold_chain_required=payload.cold_chain_required,
        )
    ]


@router.get("", response_model=Page[LogisticsOut], summary="List logistics jobs")
def list_logistics(
    session: DbSession,
    params: Pagination,
    user: CurrentUser,
    role_view: Literal["all", "mine", "assigned"] = Query(
        "all",
        description=(
            "all: everything the caller may see; mine: jobs on the caller's own "
            "orders; assigned: jobs booked to a transport account"
        ),
    ),
    provider_user_id: uuid.UUID | None = Query(
        None, description="Restrict to one transporter account"
    ),
    status_list: list[LogisticsStatus] | None = Query(
        None, alias="status", description="Restrict to these job statuses"
    ),
) -> Page[LogisticsOut]:
    """List transport jobs, most recently created first.

    Visibility follows the caller's role: sellers and buyers see jobs on their
    own orders, transporters see jobs booked to them, admins see everything.
    """
    service = LogisticsService(session)
    items, total = service.list_requests(
        user=user,
        role_view=ROLE_VIEWS[role_view],
        provider_user_id=provider_user_id,
        status=status_list,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[LogisticsOut].build(
        [_logistics_out(service, request) for request in items], total, params
    )


@router.get(
    "/orders/{order_id}",
    response_model=dict[str, Any],
    summary="Logistics job for an order",
)
def logistics_for_order(
    order_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """The job arranged for this order, or an empty result when none exists yet."""
    service = LogisticsService(session)
    request = service.get_for_order(order_id)
    return {
        "order_id": order_id,
        "logistics": _logistics_out(service, request) if request else None,
    }


@router.post(
    "",
    response_model=LogisticsOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request transport for an order",
)
def create_logistics(
    payload: LogisticsCreate, session: DbSession, user: LogisticsRequester
) -> LogisticsOut:
    """Raise a transport request for an order the caller is party to.

    An order may carry only one job; the cost estimate falls back to the
    cheapest lane option when the caller does not supply one.
    """
    service = LogisticsService(session)
    request = service.create_request(payload, user)
    session.commit()
    return _logistics_out(service, request)


@router.get("/{request_id}", response_model=LogisticsOut, summary="Logistics job detail")
def get_logistics(request_id: uuid.UUID, session: DbSession, user: CurrentUser) -> LogisticsOut:
    """A single transport job with its full status history."""
    service = LogisticsService(session)
    return _logistics_out(service, service.get_request(request_id))


@router.post("/{request_id}/assign", response_model=LogisticsOut, summary="Assign a transporter")
def assign_logistics(
    request_id: uuid.UUID,
    payload: AssignRequest,
    session: DbSession,
    user: LogisticsAssigner,
) -> LogisticsOut:
    """Book a requested job to a transport account.

    Only admins and logistics partners may accept work, and only a job still
    awaiting a transporter can be assigned.
    """
    service = LogisticsService(session)
    request = service.assign(request_id, payload.provider_user_id, user)
    session.commit()
    return _logistics_out(service, request)


@router.patch("/{request_id}", response_model=LogisticsOut, summary="Update a logistics job")
def update_logistics(
    request_id: uuid.UUID,
    payload: LogisticsUpdate,
    session: DbSession,
    user: LogisticsUpdater,
) -> LogisticsOut:
    """Patch job details or advance its status.

    Only the assigned transporter or an admin may edit; status moves are
    checked against the job state machine and mirrored onto the order.
    """
    service = LogisticsService(session)
    request = service.update(request_id, payload, user)
    session.commit()
    return _logistics_out(service, request)


@router.post(
    "/{request_id}/cancel",
    response_model=LogisticsOut,
    summary="Cancel a logistics job",
)
def cancel_logistics(
    request_id: uuid.UUID,
    session: DbSession,
    user: LogisticsRequester,
    reason: str | None = Query(None, max_length=255),
) -> LogisticsOut:
    """Cancel a job that has not been delivered yet.

    Allowed for admins, the assigned transporter, and the buyer or seller on
    the underlying order; the reason is kept in the status history.
    """
    service = LogisticsService(session)
    request = service.cancel(request_id, user, reason=reason)
    session.commit()
    return _logistics_out(service, request)


__all__ = ["router"]
