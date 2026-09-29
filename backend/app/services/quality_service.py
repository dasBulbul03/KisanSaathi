"""Quality inspection and grading service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import (
    InspectionStatus,
    NotificationType,
    OrderStatus,
    QualityGrade,
    UserRole,
)
from app.core.exceptions import (
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.models import (
    FarmLot,
    Order,
    QualityAttribute,
    QualityInspection,
    QualityMeasurement,
    User,
)
from app.repositories.markets import QualityAttributeRepository
from app.repositories.operations import QualityInspectionRepository
from app.repositories.trade import LotRepository, OrderRepository
from app.schemas.operations import QualityInspectionCreate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService

logger = get_logger(__name__)

GRADE_RANK: dict[QualityGrade, int] = {
    QualityGrade.GRADE_A: 3,
    QualityGrade.GRADE_B: 2,
    QualityGrade.GRADE_C: 1,
}

DEMO_NOTE = "Demo inspection record generated for the hackathon dataset."


class QualityService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.inspections = QualityInspectionRepository(QualityInspection, session)
        self.lots = LotRepository(FarmLot, session)
        self.orders = OrderRepository(Order, session)
        self.attributes = QualityAttributeRepository(QualityAttribute, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    # ------------------------------------------------------------- lookups
    def get(self, inspection_id: uuid.UUID) -> QualityInspection:
        inspection = self.inspections.get_detailed(inspection_id)
        if inspection is None:
            raise NotFoundError(
                "The quality inspection could not be found.", code="INSPECTION_NOT_FOUND"
            )
        return inspection

    def _active_order_for_lot(self, lot_id: uuid.UUID) -> Order | None:
        """The newest non-cancelled order for a lot, if one exists."""
        from app.core.enums import OrderStatus

        return (
            self.session.query(Order)
            .filter(Order.lot_id == lot_id, Order.status != OrderStatus.CANCELLED)
            .order_by(Order.created_at.desc())
            .first()
        )

    def _is_order_party(self, lot_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """True when the user is a buyer or seller on any order for this lot."""
        from app.core.enums import OrderStatus

        return (
            self.session.query(Order.id)
            .filter(
                Order.lot_id == lot_id,
                (Order.buyer_user_id == user_id) | (Order.seller_user_id == user_id),
                Order.status != OrderStatus.CANCELLED,
            )
            .first()
            is not None
        )

    def definitions_for_commodity(self, commodity_id: uuid.UUID) -> list[QualityAttribute]:
        return self.attributes.for_commodity(commodity_id)

    def list_inspections(
        self,
        *,
        lot_id: uuid.UUID | None = None,
        order_id: uuid.UUID | None = None,
        inspector_user_id: uuid.UUID | None = None,
        status: InspectionStatus | None = None,
        grade: QualityGrade | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[QualityInspection], int]:
        stmt = self.inspections.search_query(
            lot_id=lot_id,
            order_id=order_id,
            inspector_user_id=inspector_user_id,
            status=[status] if status else None,
            grade=[grade] if grade else None,
        )
        return self.inspections.paginate(stmt=stmt, page=page, page_size=page_size)

    # ------------------------------------------------------------ mutation
    def create_inspection(self, payload: QualityInspectionCreate, user: User) -> QualityInspection:
        lot: FarmLot | None = None
        order: Order | None = None
        if payload.lot_id:
            lot = self.lots.get(payload.lot_id)
            if lot is None:
                raise NotFoundError("The referenced lot could not be found.", code="LOT_NOT_FOUND")
        if payload.order_id:
            order = self.orders.get(payload.order_id)
            if order is None:
                raise NotFoundError(
                    "The referenced order could not be found.", code="ORDER_NOT_FOUND"
                )
        elif lot is not None:
            # Link a lot-level inspection to its live order so quality events
            # advance the trade workflow instead of sitting in isolation.
            order = self._active_order_for_lot(lot.id)
        if order is not None:
            if user.id not in (order.buyer_user_id, order.seller_user_id) and user.role not in (
                UserRole.ADMIN,
                UserRole.QUALITY_INSPECTOR,
            ):
                raise PermissionDeniedError(
                    "You are not a party to this order.", code="ORDER_FORBIDDEN"
                )
        elif lot is not None:
            is_staff = user.role in (UserRole.ADMIN, UserRole.QUALITY_INSPECTOR)
            if lot.seller_user_id != user.id and not is_staff:
                # A buyer who has an accepted order on this lot may report a
                # quality issue (that is how a mismatch dispute is opened).
                if not self._is_order_party(lot.id, user.id):
                    raise PermissionDeniedError(
                        "You can only submit inspections for your own lots or for "
                        "lots you have an order on.",
                        code="LOT_NOT_OWNER",
                    )

        auto_grade = payload.grade
        attribute_map = {
            a.id: a
            for a in self.definitions_for_commodity(
                (order.commodity_id if order else lot.commodity_id if lot else None)
                or uuid.UUID(int=0)
            )
        }

        inspection = QualityInspection(
            lot_id=lot.id if lot else None,
            order_id=order.id if order else None,
            inspector_user_id=user.id,
            inspection_type=payload.inspection_type,
            inspected_at=payload.inspected_at or datetime.now(UTC),
            grade=auto_grade,
            # Inspector submissions start as PENDING; only an inspector/admin confirms.
            status=(
                InspectionStatus.CONFIRMED
                if user.role in (UserRole.QUALITY_INSPECTOR, UserRole.ADMIN)
                else InspectionStatus.PENDING
            ),
            attributes=payload.attributes or {},
            moisture_percent=payload.moisture_percent,
            damage_percent=payload.damage_percent,
            notes=payload.notes,
            is_demo=False,
        )
        self.session.add(inspection)
        self.session.flush()

        for measurement in payload.measurements:
            attribute = attribute_map.get(measurement.attribute_id)
            self.session.add(
                QualityMeasurement(
                    inspection_id=inspection.id,
                    attribute_id=measurement.attribute_id,
                    numeric_value=measurement.numeric_value,
                    text_value=measurement.text_value,
                    grade_band=(
                        self._band(attribute, measurement.numeric_value) if attribute else None
                    ),
                )
            )
        self.session.flush()

        if inspection.status is InspectionStatus.CONFIRMED and order is not None:
            from app.services.order_service import OrderService

            service = OrderService(self.session)
            if service.can_transition(order, OrderStatus.QUALITY_CONFIRMED, user):
                from app.schemas.trade import OrderStatusUpdate

                service.update_status(
                    order.id,
                    OrderStatusUpdate(
                        status=OrderStatus.QUALITY_CONFIRMED,
                        note=f"Quality confirmed as {payload.grade.value}",
                    ),
                    user,
                )
        if order is not None:
            self.notifications.notify(
                order.seller_user_id,
                notification_type=NotificationType.QUALITY_INSPECTION,
                title=f"Quality inspection on order {order.order_number}",
                body=(
                    f"Grade {payload.grade.value} recorded by {user.full_name}. "
                    f"Status: {inspection.status.value.lower()}."
                ),
                link="/inspections",
            )
        self.audit.record(
            action="QUALITY_INSPECTION_CREATED",
            entity_type="quality_inspection",
            entity_id=inspection.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={
                "grade": payload.grade.value,
                "status": inspection.status.value,
                "lot_id": str(lot.id) if lot else None,
                "order_id": str(order.id) if order else None,
            },
        )
        return self.get(inspection.id)

    def verify_inspection(
        self,
        inspection_id: uuid.UUID,
        *,
        approve: bool,
        user: User,
        notes: str | None = None,
    ) -> QualityInspection:
        if user.role not in (UserRole.ADMIN, UserRole.QUALITY_INSPECTOR):
            raise PermissionDeniedError(
                "Only a quality inspector or administrator can verify a grade.",
                code="QUALITY_VERIFY_FORBIDDEN",
            )
        inspection = self.get(inspection_id)
        if inspection.status is not InspectionStatus.PENDING:
            raise InvalidStateTransitionError(
                "This inspection has already been verified.", code="INSPECTION_ALREADY_VERIFIED"
            )
        before = inspection.status.value
        inspection.status = InspectionStatus.CONFIRMED if approve else InspectionStatus.REJECTED
        if notes:
            inspection.notes = f"{inspection.notes or ''}\n[Reviewer] {notes}".strip()
        self.session.flush()

        target: User | None = None
        if inspection.lot_id:
            lot = self.lots.get(inspection.lot_id)
            target = lot.seller if lot else None
        elif inspection.order_id:
            order = self.orders.get(inspection.order_id)
            if order:
                target = order.seller
        if target is not None:
            self.notifications.notify(
                target.id,
                notification_type=NotificationType.QUALITY_INSPECTION,
                title=f"Quality inspection {inspection.status.value.lower()}",
                body=(
                    f"Grade {inspection.grade.value} was "
                    f"{'confirmed' if approve else 'rejected'} by {user.full_name}."
                ),
                link="/inspections",
            )
        self.audit.record(
            action="QUALITY_INSPECTION_VERIFIED" if approve else "QUALITY_INSPECTION_REJECTED",
            entity_type="quality_inspection",
            entity_id=inspection.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before={"status": before},
            after={"status": inspection.status.value},
            note=notes,
        )
        return self.get(inspection_id)

    def suggest_grade(self, commodity_id: uuid.UUID, values: dict[str, float]) -> dict[str, Any]:
        """Derive a suggested grade from commodity-specific parameter values."""
        definitions = self.definitions_for_commodity(commodity_id)
        if not definitions:
            return {
                "suggested_grade": None,
                "reason": "No quality parameters are configured for this commodity.",
                "checks": [],
            }
        checks: list[dict[str, Any]] = []
        satisfied = 0
        for attribute in definitions:
            raw = values.get(attribute.code)
            if raw is None:
                continue
            ok = (
                attribute.ideal_min is not None
                and attribute.ideal_max is not None
                and attribute.ideal_min <= raw <= attribute.ideal_max
            ) or (attribute.ideal_min is None and raw >= (attribute.grade_b_min or 0))
            checks.append(
                {
                    "code": attribute.code,
                    "label": attribute.label,
                    "unit": attribute.unit,
                    "value": raw,
                    "ideal_min": attribute.ideal_min,
                    "ideal_max": attribute.ideal_max,
                    "satisfied": bool(ok),
                }
            )
            satisfied += 1 if ok else 0
        if not checks:
            return {
                "suggested_grade": None,
                "reason": "Provide at least one quality parameter to get a suggestion.",
                "checks": [],
            }
        ratio = satisfied / len(checks)
        if ratio >= 0.85:
            grade = QualityGrade.GRADE_A
        elif ratio >= 0.5:
            grade = QualityGrade.GRADE_B
        else:
            grade = QualityGrade.GRADE_C
        return {
            "suggested_grade": grade,
            "reason": (
                f"{satisfied} of {len(checks)} recorded parameters fall inside the ideal "
                f"range for {grade.label}."
            ),
            "checks": checks,
        }

    @staticmethod
    def _band(attribute: QualityAttribute, value: float | None) -> str | None:
        if value is None:
            return None
        if attribute.grade_a_min is None and attribute.grade_b_min is None:
            # The parameter is judged by its ideal range only (rot, moisture,
            # impurity). Reporting "C" here would invent a bad grade.
            return None
        if attribute.grade_a_min is not None and value >= attribute.grade_a_min:
            return "A"
        if attribute.grade_b_min is not None and value >= attribute.grade_b_min:
            return "B"
        return "C"

    # -------------------------------------------------------- presentation
    def enrich(self, inspection: QualityInspection) -> dict[str, Any]:
        return {
            "id": inspection.id,
            "lot_id": inspection.lot_id,
            "order_id": inspection.order_id,
            "inspector_user_id": inspection.inspector_user_id,
            "inspector_name": inspection.inspector.full_name if inspection.inspector else None,
            "inspection_type": inspection.inspection_type,
            "inspected_at": inspection.inspected_at,
            "grade": inspection.grade,
            "status": inspection.status,
            "attributes": inspection.attributes or {},
            "moisture_percent": inspection.moisture_percent,
            "damage_percent": inspection.damage_percent,
            "notes": inspection.notes,
            "is_demo": inspection.is_demo,
            "created_at": inspection.created_at,
            "measurements": [
                {
                    "id": measurement.id,
                    "attribute_id": measurement.attribute_id,
                    "attribute_label": measurement.attribute.label
                    if measurement.attribute
                    else None,
                    "attribute_unit": measurement.attribute.unit if measurement.attribute else None,
                    "numeric_value": measurement.numeric_value,
                    "text_value": measurement.text_value,
                    "grade_band": measurement.grade_band,
                }
                for measurement in (inspection.measurements or [])
            ],
        }

    def pending_verifications(self) -> list[QualityInspection]:
        return self.inspections.pending_verification()
