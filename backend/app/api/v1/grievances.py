"""Grievance and dispute endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, DbSession, Pagination, require_permissions
from app.core.enums import GrievanceCategory, GrievanceStatus, Priority, UserRole
from app.core.rbac import GRIEVANCE_COMMENT, GRIEVANCE_CREATE, GRIEVANCE_READ
from app.models import Grievance, GrievanceComment, User
from app.schemas.common import Page
from app.schemas.operations import (
    GrievanceCommentCreate,
    GrievanceCommentOut,
    GrievanceCreate,
    GrievanceOut,
    GrievanceUpdate,
)
from app.services.grievance_service import GrievanceService

router = APIRouter(prefix="/grievances", tags=["grievances"])

GrievanceReader = Annotated[User, Depends(require_permissions(GRIEVANCE_READ))]
GrievanceCreator = Annotated[User, Depends(require_permissions(GRIEVANCE_CREATE))]
# There is no dedicated update permission: every party to a ticket may annotate
# it, and the service rejects the changes a reporter is not allowed to make.
GrievanceUpdater = Annotated[User, Depends(require_permissions(GRIEVANCE_READ))]
GrievanceCommenter = Annotated[User, Depends(require_permissions(GRIEVANCE_COMMENT))]


def _grievance_out(service: GrievanceService, grievance: Grievance, viewer: User) -> GrievanceOut:
    """Serialise a grievance with its history, comment count and derived flags.

    The enrich payload also carries ``category_label``, ``is_overdue``, the full
    comment thread and the evidence list; those are outside the GrievanceOut
    contract and dropped here.
    """
    return GrievanceOut.model_validate(service.enrich(grievance, viewer=viewer))


def _comment_out(comment: GrievanceComment) -> GrievanceCommentOut:
    """Serialise a thread entry with its author context.

    ``author_name`` and ``author_role`` have no ORM backing column, so they are
    resolved from the author relationship rather than left blank.
    """
    author = comment.author
    return GrievanceCommentOut(
        id=comment.id,
        grievance_id=comment.grievance_id,
        author_user_id=comment.author_user_id,
        author_name=author.full_name if author else None,
        author_role=(author.primary_role.name.value if author and author.primary_role else None),
        body=comment.body,
        is_internal=comment.is_internal,
        created_at=comment.created_at,
    )


@router.get("", response_model=Page[GrievanceOut], summary="List grievances")
def list_grievances(
    session: DbSession,
    params: Pagination,
    user: GrievanceReader,
    status_list: list[GrievanceStatus] | None = Query(
        None, alias="status", description="Restrict to these grievance statuses"
    ),
    priority_list: list[Priority] | None = Query(
        None, alias="priority", description="Restrict to these priorities"
    ),
    category: GrievanceCategory | None = Query(
        None, description="Restrict to one grievance category"
    ),
    assigned_to_user_id: uuid.UUID | None = Query(None, description="Filter by the assignee"),
) -> Page[GrievanceOut]:
    """Tickets the caller raised or is a party to; administrators see all of them.

    Internal notes never appear in the list, whatever the caller's role.
    """
    service = GrievanceService(session)
    items, total = service.list_grievances(
        user=user,
        status=status_list,
        priority=priority_list,
        category=category,
        assigned_to_user_id=assigned_to_user_id,
        page=params.page,
        page_size=params.page_size,
    )
    return Page[GrievanceOut].build(
        [_grievance_out(service, grievance, viewer=user) for grievance in items],
        total,
        params,
    )


@router.get("/summary", response_model=dict[str, int], summary="Grievance counts by status")
def grievance_summary(session: DbSession, user: GrievanceReader) -> dict[str, int]:
    """Ticket counts per status (open, under review, resolved...).

    This is a **platform-wide** tally, not the caller's own tickets:
    ``counts_by_status`` takes no user argument and the service exposes no
    user-scoped variant.
    """
    return GrievanceService(session).counts_by_status()


@router.post(
    "",
    response_model=GrievanceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a grievance",
)
def create_grievance(
    payload: GrievanceCreate, session: DbSession, user: GrievanceCreator
) -> GrievanceOut:
    """Raise a ticket against a counterparty, linked to an order when there is one.

    Naming an order requires being a party to it, and the counterparty defaults
    to the other side of that order. The resolution due date follows the SLA for
    the chosen priority.
    """
    service = GrievanceService(session)
    grievance = service.create(payload, user)
    session.commit()
    return _grievance_out(service, grievance, viewer=user)


@router.get("/{grievance_id}", response_model=GrievanceOut, summary="Grievance detail")
def get_grievance(grievance_id: uuid.UUID, session: DbSession, user: CurrentUser) -> GrievanceOut:
    """Full ticket with its status history, comment count and evidence.

    ``enrich`` only hides internal notes, so visibility is asserted separately:
    the reporter, the accused, the assignee and administrators may read a ticket.
    """
    service = GrievanceService(session)
    grievance = service.get(grievance_id)
    service.assert_visible(grievance, user)
    return _grievance_out(service, grievance, viewer=user)


@router.patch("/{grievance_id}", response_model=GrievanceOut, summary="Update a grievance")
def update_grievance(
    grievance_id: uuid.UUID,
    payload: GrievanceUpdate,
    session: DbSession,
    user: GrievanceUpdater,
) -> GrievanceOut:
    """Change the status, priority, assignee or resolution of a ticket.

    Status moves follow the grievance state machine and are administrator-only;
    other parties may still adjust priority or add a resolution note. Closing a
    ticket flags the linked payments as disputed.
    """
    service = GrievanceService(session)
    grievance = service.update(grievance_id, payload, user)
    session.commit()
    return _grievance_out(service, grievance, viewer=user)


@router.post(
    "/{grievance_id}/comments",
    response_model=GrievanceCommentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to a grievance",
)
def add_comment(
    grievance_id: uuid.UUID,
    payload: GrievanceCommentCreate,
    session: DbSession,
    user: GrievanceCommenter,
) -> GrievanceCommentOut:
    """Append a reply to the ticket thread and notify the other parties.

    ``is_internal`` notes are administrator-only. The first administrator reply
    on an open ticket moves it to under review automatically.
    """
    service = GrievanceService(session)
    comment = service.add_comment(grievance_id, payload.body, user, is_internal=payload.is_internal)
    session.commit()
    return _comment_out(comment)


@router.get(
    "/{grievance_id}/comments",
    response_model=list[GrievanceCommentOut],
    summary="Comment thread for a grievance",
)
def list_comments(
    grievance_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> list[GrievanceCommentOut]:
    """The ticket's discussion, oldest message first.

    Internal notes are administrator-only and are withheld from every other
    viewer, who may still read the ticket itself.
    """
    service = GrievanceService(session)
    grievance = service.get(grievance_id)
    service.assert_visible(grievance, user)
    return [
        _comment_out(comment)
        for comment in grievance.comments
        if user.role is UserRole.ADMIN or not comment.is_internal
    ]


@router.post(
    "/{grievance_id}/escalate",
    response_model=GrievanceOut,
    summary="Escalate a grievance",
)
def escalate_grievance(
    grievance_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    note: str | None = Query(
        None, max_length=4000, description="Why the ticket is being escalated"
    ),
) -> GrievanceOut:
    """Raise the ticket to the escalated state, recording the reason.

    Escalation is a status change, so only an administrator may perform it; the
    note is stored as the resolution text of the transition.
    """
    service = GrievanceService(session)
    grievance = service.escalate(grievance_id, user, note=note)
    session.commit()
    return _grievance_out(service, grievance, viewer=user)


__all__ = ["router"]
