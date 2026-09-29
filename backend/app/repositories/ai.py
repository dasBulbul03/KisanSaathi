"""AI persistence repositories."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from app.models import AIConversation, AIMessage, AIRecommendation
from app.repositories.base import BaseRepository


class RecommendationRepository(BaseRepository[AIRecommendation]):
    def for_user(
        self, user_id: uuid.UUID, *, kind: str | None = None, limit: int = 20
    ) -> list[AIRecommendation]:
        filters: dict = {"user_id": user_id}
        if kind:
            filters["kind"] = kind
        return self.find_all(filters=filters, order_by=["-created_at"], limit=limit)


class ConversationRepository(BaseRepository[AIConversation]):
    def for_user(self, user_id: uuid.UUID, *, limit: int = 50) -> list[AIConversation]:
        return self.find_all(
            filters={"user_id": user_id, "is_deleted": False},
            order_by=["-created_at"],
            limit=limit,
        )

    def get_with_messages(self, conversation_id: uuid.UUID) -> AIConversation | None:
        stmt = (
            self._base_query()
            .options(selectinload(AIConversation.messages))
            .where(AIConversation.id == conversation_id)
        )
        return self.session.execute(stmt).unique().scalar_one_or_none()

    def owned_by(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> AIConversation | None:
        stmt = (
            self._base_query()
            .options(selectinload(AIConversation.messages))
            .where(AIConversation.id == conversation_id, AIConversation.user_id == user_id)
        )
        return self.session.execute(stmt).unique().scalar_one_or_none()


class MessageRepository(BaseRepository[AIMessage]):
    def recent(self, conversation_id: uuid.UUID, *, limit: int = 12) -> list[AIMessage]:
        stmt: Select = (
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.created_at.desc())
            .limit(limit)
        )
        rows = list(self.session.execute(stmt).scalars().all())
        return list(reversed(rows))
