"""Quality parameter, inspection and grading endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, Pagination, require_permissions
from app.core.enums import InspectionStatus, QualityGrade
from app.core.rbac import QUALITY_READ, QUALITY_SUBMIT, QUALITY_VERIFY
from app.models import User
from app.schemas.common import Page
from app.schemas.market import QualityAttributeOut
from app.schemas.operations import QualityInspectionCreate, QualityInspectionOut
from app.services.quality_service import QualityService

router = APIRouter(prefix="/quality", tags=["quality"])

QualityReader = Annotated[User, Depends(require_permissions(QUALITY_READ))]
QualitySubmitter = Annotated[User, Depends(require_permissions(QUALITY_SUBMIT))]
QualityVerifier = Annotated[User, Depends(require_permissions(QUALITY_VERIFY))]


class GradeSuggestionRequest(BaseModel):
    """Measured parameter values keyed by their quality attribute code."""

    commodity_id: uuid.UUID = Field(description="Commodity the grade applies to")
    values: dict[str, float] = Field(
        default_factory=dict, description="Attribute code to measured value"
    )


class VerifyRequest(BaseModel):
    """A reviewer's decision on a submitted inspection."""

    approve: bool = Field(description="Confirm the grade, or reject it")
    notes: str | None = Field(default=None, max_length=1000, description="Reason for the decision")


def _inspection_out(service: QualityService, inspection: object) -> QualityInspectionOut:
    """Serialise an inspection with its inspector and per-parameter bands."""
    return QualityInspectionOut.model_validate(service.enrich(inspection))


@router.get(
    "/attributes/{commodity_id}",
    response_model=list[QualityAttributeOut],
    summary="Quality parameters for a commodity",
)
def commodity_attributes(
    commodity_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> list[QualityAttributeOut]:
    """The measurable parameters of a commodity and their ideal grade ranges."""
    return QualityService(session).definitions_for_commodity(commodity_id)


@router.post(
    "/grade-suggestion",
    response_model=dict[str, Any],
    summary="Suggest a grade from measurements",
)
def suggest_grade(
    payload: GradeSuggestionRequest, session: DbSession, user: CurrentUser
) -> dict[str, Any]:
    """Derive a suggested grade from the measured parameters of a commodity.

    Advisory only - a per-parameter ``checks`` list explains which readings fell
    inside the ideal range, and the recorded grade is always the reviewer's call.
    """
    return QualityService(session).suggest_grade(payload.commodity_id, payload.values)


@router.get(
    "/inspections",
    response_model=Page[QualityInspectionOut],
    summary="List inspections",
)
def list_inspections(
    session: DbSession,
    params: Pagination,
    user: QualityReader,
    lot_id: uuid.UUID | None = Query(None, description="Filter by lot"),
    order_id: uuid.UUID | None = Query(None, description="Filter by order"),
    inspector_user_id: uuid.UUID | None = Query(None, description="Filter by inspector"),
    status: InspectionStatus | None = Query(None, description="Pending, confirmed or rejected"),
    grade: QualityGrade | None = Query(None, description="Restrict to one grade"),
) -> Page[QualityInspectionOut]:
    """Quality inspections recorded on lots and orders, newest first."""
    service = QualityService(session)
    items, total = service.list_inspections(
        lot_id=lot_id,
        order_id=order_id,
        inspector_user_id=inspector_user_id,
        status=status,
        grade=grade,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[QualityInspectionOut].build(
        [_inspection_out(service, inspection) for inspection in items], total, params
    )


@router.get(
    "/inspections/pending",
    response_model=list[QualityInspectionOut],
    summary="Inspections awaiting verification",
)
def pending_inspections(session: DbSession, user: QualityVerifier) -> list[QualityInspectionOut]:
    """The verification queue: submitted grades still awaiting a reviewer.

    Oldest first, so a grade that has been waiting longest is reviewed first.
    """
    service = QualityService(session)
    return [_inspection_out(service, inspection) for inspection in service.pending_verifications()]


@router.post(
    "/inspections",
    response_model=QualityInspectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an inspection",
)
def create_inspection(
    payload: QualityInspectionCreate, session: DbSession, user: QualitySubmitter
) -> QualityInspectionOut:
    """Record a grade for a lot or an order.

    A buyer or seller submission stays pending until an inspector confirms it;
    an inspector or admin submission is confirmed on the spot.
    """
    service = QualityService(session)
    inspection = service.create_inspection(payload, user)
    session.commit()
    return _inspection_out(service, inspection)


@router.get(
    "/inspections/{inspection_id}",
    response_model=QualityInspectionOut,
    summary="Inspection detail",
)
def get_inspection(
    inspection_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> QualityInspectionOut:
    """A single inspection with its per-parameter readings and grade bands."""
    service = QualityService(session)
    return _inspection_out(service, service.get(inspection_id))


@router.post(
    "/inspections/{inspection_id}/verify",
    response_model=QualityInspectionOut,
    summary="Verify a submitted grade",
)
def verify_inspection(
    inspection_id: uuid.UUID,
    payload: VerifyRequest,
    session: DbSession,
    user: QualityVerifier,
) -> QualityInspectionOut:
    """Confirm or reject a pending inspection.

    Confirmation can advance the linked order to quality-confirmed when the
    actor is allowed to move it; the reviewer's note is appended to the record.
    """
    service = QualityService(session)
    inspection = service.verify_inspection(
        inspection_id, approve=payload.approve, user=user, notes=payload.notes
    )
    session.commit()
    return _inspection_out(service, inspection)


__all__ = ["router"]
