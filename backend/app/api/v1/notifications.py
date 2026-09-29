"""Notification feed endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError
from app.models import Notification
from app.repositories.users import NotificationRepository
from app.schemas.operations import NotificationList, NotificationOut
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList, summary="List own notifications")
def list_notifications(
    session: DbSession,
    user: CurrentUser,
    unread_only: bool = Query(False, description="Only notifications not yet read"),
) -> NotificationList:
    """The caller's notification feed, newest first, with the unread tally.

    ``unread_count`` always reports every unread notification, even when the feed
    itself is filtered down to unread ones.
    """
    items, unread_count = NotificationService(session).list_for_user(
        user.id, unread_only=unread_only
    )
    return NotificationList(
        items=[NotificationOut.model_validate(item) for item in items],
        unread_count=unread_count,
    )


@router.get(
    "/unread-count",
    response_model=dict[str, int],
    summary="Unread notification count",
)
def unread_count(session: DbSession, user: CurrentUser) -> dict[str, int]:
    """How many notifications the caller has not read - drives the header badge.

    Counted directly in the repository so the badge does not have to load the feed.
    """
    return {"unread_count": NotificationRepository(Notification, session).unread_count(user.id)}


@router.post(
    "/read-all",
    response_model=dict[str, int],
    summary="Mark every notification as read",
)
def read_all_notifications(session: DbSession, user: CurrentUser) -> dict[str, int]:
    """Clear the caller's unread badge in one call, returning how many were read."""
    updated = NotificationService(session).mark_all_read(user.id)
    session.commit()
    return {"updated": updated}


@router.post(
    "/{notification_id}/read",
    response_model=NotificationOut,
    summary="Mark one notification as read",
)
def mark_notification_read(
    notification_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> NotificationOut:
    """Acknowledge a single notification and return it in its read state.

    A notification that does not exist, or that belongs to somebody else, is
    reported as missing so ids cannot be probed.
    """
    notification = NotificationService(session).mark_read(user.id, notification_id)
    if notification is None:
        raise NotFoundError("The notification could not be found.", code="NOTIFICATION_NOT_FOUND")
    session.commit()
    return NotificationOut.model_validate(notification)


__all__ = ["router"]
