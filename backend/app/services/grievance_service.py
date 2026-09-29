"""Grievance / dispute management service."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import (
    GrievanceStatus,
    NotificationType,
    Priority,
    UserRole,
)
from app.core.exceptions import (
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.models import Grievance, GrievanceComment, GrievanceEvidence, Order, User
from app.repositories.operations import GrievanceRepository
from app.repositories.trade import OrderRepository
from app.schemas.operations import GrievanceCreate, GrievanceUpdate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.codes import grievance_ticket

logger = get_logger(__name__)

#: Expected resolution time by priority (business days).
SLA_DAYS: dict[Priority, int] = {
    Priority.LOW: 10,
    Priority.MEDIUM: 7,
    Priority.HIGH: 3,
    Priority.CRITICAL: 1,
}

STATUS_TRANSITIONS: dict[GrievanceStatus, set[GrievanceStatus]] = {
    GrievanceStatus.OPEN: {
        GrievanceStatus.UNDER_REVIEW,
        GrievanceStatus.RESOLVED,
        GrievanceStatus.REJECTED,
    },
    GrievanceStatus.UNDER_REVIEW: {
        GrievanceStatus.RESOLVED,
        GrievanceStatus.REJECTED,
        GrievanceStatus.ESCALATED,
    },
    GrievanceStatus.ESCALATED: {GrievanceStatus.RESOLVED, GrievanceStatus.REJECTED},
    GrievanceStatus.RESOLVED: {GrievanceStatus.ESCALATED},
    GrievanceStatus.REJECTED: {GrievanceStatus.ESCALATED},
}

CATEGORY_LABELS: dict[str, str] = {
    "QUALITY_MISMATCH": "Quality mismatch",
    "QUANTITY_MISMATCH": "Quantity mismatch",
    "PAYMENT_DELAY": "Payment delay",
    "DELIVERY_ISSUE": "Delivery issue",
    "DAMAGED_GOODS": "Damaged goods",
    "BUYER_ISSUE": "Buyer issue",
    "TRANSPORTER_ISSUE": "Transporter issue",
    "OTHER": "Other",
}


class GrievanceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = GrievanceRepository(Grievance, session)
        self.orders = OrderRepository(Order, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    # ------------------------------------------------------------- helpers
    def get(self, grievance_id: uuid.UUID) -> Grievance:
        grievance = self.repo.get_detailed(grievance_id)
        if grievance is None:
            raise NotFoundError("The grievance could not be found.", code="GRIEVANCE_NOT_FOUND")
        return grievance

    def assert_visible(self, grievance: Grievance, user: User) -> None:
        if user.role is UserRole.ADMIN:
            return
        if user.id in (grievance.raised_by_user_id, grievance.against_user_id):
            return
        if grievance.assigned_to_user_id == user.id:
            return
        raise PermissionDeniedError(
            "You do not have access to this grievance.", code="GRIEVANCE_FORBIDDEN"
        )

    # ------------------------------------------------------------- queries
    def list_grievances(
        self,
        *,
        user: User,
        status: Sequence[GrievanceStatus] | None = None,
        priority: Sequence[Priority] | None = None,
        category: str | None = None,
        assigned_to_user_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Grievance], int]:
        stmt = self.repo.search_query(
            user_id=None if user.role is UserRole.ADMIN else user.id,
            user_role=user.role,
            status=status,
            priority=priority,
            assigned_to_user_id=assigned_to_user_id,
            category=category,
        )
        return self.repo.paginate(stmt=stmt, page=page, page_size=page_size)

    def counts_by_status(self) -> dict[str, int]:
        return self.repo.counts_by_status()

    # ------------------------------------------------------------ mutation
    def create(self, payload: GrievanceCreate, user: User) -> Grievance:
        order: Order | None = None
        if payload.order_id:
            order = self.orders.get(payload.order_id)
            if order is None:
                raise NotFoundError(
                    "The referenced order could not be found.", code="ORDER_NOT_FOUND"
                )
            if (
                user.id not in (order.buyer_user_id, order.seller_user_id)
                and user.role is not UserRole.ADMIN
            ):
                raise PermissionDeniedError(
                    "You are not a party to that order.", code="ORDER_FORBIDDEN"
                )
        against = payload.against_user_id
        if against is None and order is not None:
            against = (
                order.seller_user_id if user.id == order.buyer_user_id else order.buyer_user_id
            )
        grievance = Grievance(
            ticket_number=grievance_ticket(),
            raised_by_user_id=user.id,
            against_user_id=against,
            order_id=order.id if order else None,
            transaction_id=payload.transaction_id,
            category=payload.category,
            subject=payload.subject.strip(),
            description=payload.description.strip(),
            status=GrievanceStatus.OPEN,
            priority=payload.priority,
            due_date=date.today() + timedelta(days=SLA_DAYS.get(payload.priority, 7)),
            status_history=[
                {
                    "status": GrievanceStatus.OPEN.value,
                    "at": date.today().isoformat(),
                    "by": str(user.id),
                    "note": "Grievance raised",
                }
            ],
        )
        self.session.add(grievance)
        self.session.flush()
        for url in payload.evidence:
            self.session.add(
                GrievanceEvidence(
                    grievance_id=grievance.id,
                    uploaded_by_user_id=user.id,
                    url=url,
                )
            )
        self.session.flush()
        self.audit.record(
            action="GRIEVANCE_CREATED",
            entity_type="grievance",
            entity_id=grievance.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={
                "ticket_number": grievance.ticket_number,
                "category": grievance.category.value,
                "priority": grievance.priority.value,
            },
        )
        logger.info("grievance.created", ticket=grievance.ticket_number, user=str(user.id))
        if against:
            category_label = CATEGORY_LABELS.get(grievance.category.value, grievance.category.value)
            self.notifications.notify(
                against,
                notification_type=NotificationType.GRIEVANCE_UPDATE,
                title=f"Grievance {grievance.ticket_number} raised against you",
                body=(
                    f"{user.full_name} raised a {category_label} grievance: " f"{grievance.subject}"
                ),
                link="/grievances",
            )
        return self.get(grievance.id)

    def update(self, grievance_id: uuid.UUID, payload: GrievanceUpdate, user: User) -> Grievance:
        grievance = self.get(grievance_id)
        is_staff = user.role is UserRole.ADMIN
        if not is_staff:
            self.assert_visible(grievance, user)
            if payload.status is not None and payload.status is not grievance.status:
                raise PermissionDeniedError(
                    "Only an administrator can change the status of a grievance.",
                    code="GRIEVANCE_STATUS_FORBIDDEN",
                )
        data = payload.model_dump(exclude_unset=True)
        new_status = data.pop("status", None)
        before = {"status": grievance.status.value}
        if new_status is not None and new_status is not grievance.status:
            allowed = STATUS_TRANSITIONS.get(grievance.status, set())
            if new_status not in allowed:
                raise InvalidStateTransitionError(
                    f"A {grievance.status.value.lower()} grievance cannot move to "
                    f"{new_status.value.lower()}.",
                    code="GRIEVANCE_INVALID_TRANSITION",
                )
        for key, value in data.items():
            if value is not None and hasattr(grievance, key):
                setattr(grievance, key, value)
        if new_status is not None:
            grievance.status = new_status
            if new_status in (GrievanceStatus.RESOLVED, GrievanceStatus.REJECTED):
                from datetime import UTC, datetime

                grievance.resolved_at = datetime.now(UTC)
            if new_status is GrievanceStatus.UNDER_REVIEW and grievance.assigned_to_user_id is None:
                grievance.assigned_to_user_id = user.id
            grievance.status_history = list(grievance.status_history or []) + [
                {
                    "status": new_status.value,
                    "at": date.today().isoformat(),
                    "by": str(user.id),
                    "by_name": user.full_name,
                    "note": payload.resolution,
                }
            ]
            if new_status in (GrievanceStatus.RESOLVED, GrievanceStatus.REJECTED):
                from app.core.enums import PaymentStatus
                from app.models import Transaction
                from app.repositories.trade import TransactionRepository

                if grievance.transaction_id:
                    transaction = TransactionRepository(Transaction, self.session).get(
                        grievance.transaction_id
                    )
                    if transaction:
                        for payment in transaction.payments:
                            if payment.status is PaymentStatus.PAID:
                                continue
                            payment.status = PaymentStatus.DISPUTED
                            self.session.flush()
        self.session.flush()
        self.audit.record(
            action="GRIEVANCE_UPDATED",
            entity_type="grievance",
            entity_id=grievance.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before=before,
            after={"status": grievance.status.value, "priority": grievance.priority.value},
            note=payload.resolution,
        )
        self.notifications.notify(
            grievance.raised_by_user_id,
            notification_type=NotificationType.GRIEVANCE_UPDATE,
            title=f"Grievance {grievance.ticket_number} updated",
            body=(
                f"Status is now {grievance.status.value.lower()}"
                + (f": {payload.resolution}" if payload.resolution else ".")
            ),
            link="/grievances",
        )
        return self.get(grievance_id)

    def add_comment(
        self,
        grievance_id: uuid.UUID,
        body: str,
        user: User,
        *,
        is_internal: bool = False,
    ) -> GrievanceComment:
        grievance = self.get(grievance_id)
        self.assert_visible(grievance, user)
        if is_internal and user.role is not UserRole.ADMIN:
            raise PermissionDeniedError(
                "Only administrators can add internal notes.", code="INTERNAL_NOTE_FORBIDDEN"
            )
        comment = GrievanceComment(
            grievance_id=grievance.id,
            author_user_id=user.id,
            body=body.strip(),
            is_internal=is_internal,
        )
        self.session.add(comment)
        self.session.flush()
        # The relationship may already be loaded in this session, so drop the
        # cached collection to keep ``enrich`` and API responses accurate.
        self.session.expire(grievance, ["comments", "evidence"])
        if grievance.status is GrievanceStatus.OPEN and user.role is UserRole.ADMIN:
            self.update(
                grievance_id,
                GrievanceUpdate(status=GrievanceStatus.UNDER_REVIEW),
                user,
            )
        recipients = {
            grievance.raised_by_user_id,
            grievance.against_user_id,
            grievance.assigned_to_user_id,
        } - {None, user.id}
        self.notifications.notify_many(
            [r for r in recipients if r],
            notification_type=NotificationType.GRIEVANCE_UPDATE,
            title=f"New reply on {grievance.ticket_number}",
            body=body[:180],
            link="/grievances",
        )
        return comment

    def escalate(
        self, grievance_id: uuid.UUID, user: User, *, note: str | None = None
    ) -> Grievance:
        return self.update(
            grievance_id,
            GrievanceUpdate(status=GrievanceStatus.ESCALATED, resolution=note),
            user,
        )

    # -------------------------------------------------------- presentation
    def enrich(self, grievance: Grievance, viewer: User | None = None) -> dict[str, Any]:
        comments = [
            c
            for c in (grievance.comments or [])
            if viewer is None or viewer.role is UserRole.ADMIN or not c.is_internal
        ]
        due = grievance.due_date
        return {
            "id": grievance.id,
            "ticket_number": grievance.ticket_number,
            "raised_by_user_id": grievance.raised_by_user_id,
            "raised_by_name": grievance.raised_by.full_name if grievance.raised_by else None,
            "against_user_id": grievance.against_user_id,
            "against_name": grievance.against.full_name if grievance.against else None,
            "order_id": grievance.order_id,
            "order_number": grievance.order.order_number if grievance.order else None,
            "transaction_id": grievance.transaction_id,
            "category": grievance.category,
            "category_label": CATEGORY_LABELS.get(
                grievance.category.value, grievance.category.value
            ),
            "subject": grievance.subject,
            "description": grievance.description,
            "status": grievance.status,
            "priority": grievance.priority,
            "assigned_to_user_id": grievance.assigned_to_user_id,
            "assigned_to_name": grievance.assigned_to.full_name if grievance.assigned_to else None,
            "resolution": grievance.resolution,
            "resolved_at": grievance.resolved_at,
            "due_date": due,
            "is_overdue": bool(
                due
                and due < date.today()
                and grievance.status in (GrievanceStatus.OPEN, GrievanceStatus.UNDER_REVIEW)
            ),
            "status_history": grievance.status_history or [],
            "comment_count": len(comments),
            "comments": [
                {
                    "id": comment.id,
                    "grievance_id": comment.grievance_id,
                    "author_user_id": comment.author_user_id,
                    "author_name": comment.author.full_name if comment.author else None,
                    "author_role": comment.author.primary_role.name.value
                    if comment.author and comment.author.primary_role
                    else None,
                    "body": comment.body,
                    "is_internal": comment.is_internal,
                    "created_at": comment.created_at,
                }
                for comment in comments
            ],
            "evidence": [
                {"id": e.id, "url": e.url, "description": e.description, "file_name": e.file_name}
                for e in (grievance.evidence or [])
            ],
            "created_at": grievance.created_at,
            "updated_at": grievance.updated_at,
        }
