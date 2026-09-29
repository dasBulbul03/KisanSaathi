"""Notification service. Delivery channels are pluggable via integrations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import NotificationType
from app.core.logging import get_logger
from app.models import Notification
from app.repositories.users import NotificationRepository

logger = get_logger(__name__)


class NotificationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = NotificationRepository(Notification, session)

    def notify(
        self,
        user_id: uuid.UUID,
        *,
        notification_type: NotificationType | str,
        title: str,
        body: str,
        link: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Notification:
        notification = self.repo.create(
            user_id=user_id,
            title=title[:200],
            body=body,
            notification_type=str(notification_type),
            link=link,
            data=data or {},
            is_read=False,
        )
        self.session.flush()
        logger.info(
            "notification.created",
            user_id=str(user_id),
            type=str(notification_type),
        )
        return notification

    def notify_many(self, user_ids: list[uuid.UUID], **kwargs: Any) -> list[Notification]:
        return [self.notify(user_id, **kwargs) for user_id in dict.fromkeys(user_ids)]

    def list_for_user(
        self, user_id: uuid.UUID, *, unread_only: bool = False
    ) -> tuple[list[Notification], int]:
        items = self.repo.for_user(user_id, unread_only=unread_only)
        unread = self.repo.unread_count(user_id)
        return items, unread

    def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification | None:
        notification = self.repo.get(notification_id)
        if notification is None or notification.user_id != user_id:
            return None
        return self.repo.mark_read(notification)

    def mark_all_read(self, user_id: uuid.UUID) -> int:
        return self.repo.mark_all_read(user_id)
