"""AI persistence: recommendations, conversations and messages."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AIConversationMode, ConfidenceLevel, MessageRole
from app.db.base import JSON, Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.user import User


class AIRecommendation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A cached, explainable output of the recommendation engine or the LLM."""

    __tablename__ = "ai_recommendations"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    commodity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("commodities.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    factors: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        SAEnum(ConfidenceLevel, name="ai_confidence", native_enum=False, length=12),
        default=ConfidenceLevel.MEDIUM,
        nullable=False,
    )
    engine: Mapped[str] = mapped_column(String(32), default="rules", nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    provider: Mapped[str | None] = mapped_column(String(60))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disclaimer: Mapped[str | None] = mapped_column(String(400))
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    user: Mapped[User] = relationship()

    __table_args__ = (Index("ix_ai_rec_user_kind", "user_id", "kind"),)


class AIConversation(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "ai_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="New conversation", nullable=False)
    mode: Mapped[AIConversationMode] = mapped_column(
        SAEnum(AIConversationMode, name="ai_conversation_mode", native_enum=False, length=32),
        default=AIConversationMode.FARMER_ASSISTANT,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    total_messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped[User] = relationship()
    messages: Mapped[list[AIMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AIMessage.created_at",
    )


class AIMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ai_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        SAEnum(MessageRole, name="ai_message_role", native_enum=False, length=16),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(80))
    tool_arguments: Mapped[dict | None] = mapped_column(JSON)
    tool_result_summary: Mapped[dict | None] = mapped_column(JSON)
    data: Mapped[dict | None] = mapped_column(JSON)
    provider: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    feedback: Mapped[str | None] = mapped_column(String(16))

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")
