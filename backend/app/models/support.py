"""Payment tracking and grievance management models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    GrievanceCategory,
    GrievanceStatus,
    PaymentMethod,
    PaymentStatus,
    Priority,
)
from app.db.base import JSON, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.trade import Order, Transaction
    from app.models.user import User


class Payment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tracks a payment obligation. The platform never moves money itself -
    a payment gateway integration is a pluggable module (see PaymentGateway)."""

    __tablename__ = "payments"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    payer_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payee_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, name="payment_status", native_enum=False, length=16),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True,
    )
    method: Mapped[PaymentMethod] = mapped_column(
        SAEnum(PaymentMethod, name="payment_method", native_enum=False, length=24),
        default=PaymentMethod.BANK_TRANSFER,
        nullable=False,
    )
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    reference_number: Mapped[str | None] = mapped_column(String(120), index=True)
    gateway_reference: Mapped[str | None] = mapped_column(String(120))
    initiated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    transaction: Mapped[Transaction] = relationship(back_populates="payments")
    payer: Mapped[User] = relationship(foreign_keys=[payer_user_id])
    payee: Mapped[User] = relationship(foreign_keys=[payee_user_id])

    __table_args__ = (Index("ix_payments_status_due", "status", "due_date"),)


class Grievance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "grievances"

    ticket_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    raised_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    against_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[GrievanceCategory] = mapped_column(
        SAEnum(GrievanceCategory, name="grievance_category", native_enum=False, length=32),
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GrievanceStatus] = mapped_column(
        SAEnum(GrievanceStatus, name="grievance_status", native_enum=False, length=24),
        default=GrievanceStatus.OPEN,
        nullable=False,
        index=True,
    )
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, name="grievance_priority", native_enum=False, length=16),
        default=Priority.MEDIUM,
        nullable=False,
        index=True,
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    due_date: Mapped[date | None] = mapped_column(Date)
    status_history: Mapped[list] = mapped_column(JSON, default=list)

    raised_by: Mapped[User] = relationship(foreign_keys=[raised_by_user_id])
    against: Mapped[User | None] = relationship(foreign_keys=[against_user_id])
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_user_id])
    order: Mapped[Order | None] = relationship()
    comments: Mapped[list[GrievanceComment]] = relationship(
        back_populates="grievance",
        cascade="all, delete-orphan",
        order_by="GrievanceComment.created_at",
    )
    evidence: Mapped[list[GrievanceEvidence]] = relationship(
        back_populates="grievance", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_grievances_status_priority", "status", "priority"),)


class GrievanceComment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "grievance_comments"

    grievance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("grievances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    grievance: Mapped[Grievance] = relationship(back_populates="comments")
    author: Mapped[User] = relationship(foreign_keys=[author_user_id])


class GrievanceEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "grievance_evidence"

    grievance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("grievances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(120))
    size_bytes: Mapped[int | None] = mapped_column()
    description: Mapped[str | None] = mapped_column(String(300))

    grievance: Mapped[Grievance] = relationship(back_populates="evidence")
