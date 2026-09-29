"""Operations repositories: logistics, storage, payments, grievances, audit."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.core.enums import (
    GrievanceStatus,
    InspectionStatus,
    LogisticsStatus,
    PaymentStatus,
    Priority,
    QualityGrade,
    UserRole,
)
from app.models import (
    AuditLog,
    Grievance,
    LogisticsQuote,
    LogisticsRequest,
    Order,
    Payment,
    QualityInspection,
    QualityMeasurement,
    StorageFacility,
    Transaction,
)
from app.repositories.base import BaseRepository


class LogisticsRepository(BaseRepository[LogisticsRequest]):
    def _with_refs(self) -> Select:
        return self._base_query().options(
            joinedload(LogisticsRequest.order).joinedload(Order.commodity),
            joinedload(LogisticsRequest.provider),
        )

    def get_detailed(self, request_id: uuid.UUID) -> LogisticsRequest | None:
        return (
            self.session.execute(self._with_refs().where(LogisticsRequest.id == request_id))
            .unique()
            .scalar_one_or_none()
        )

    def for_order(self, order_id: uuid.UUID) -> LogisticsRequest | None:
        return self.find_one_by(order_id=order_id)

    def search_query(
        self,
        *,
        provider_user_id: uuid.UUID | None = None,
        status: Sequence[LogisticsStatus] | None = None,
        order_id: uuid.UUID | None = None,
        pickup_district: str | None = None,
        destination_district: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> Select:
        stmt = self._with_refs()
        if provider_user_id:
            stmt = stmt.where(LogisticsRequest.provider_user_id == provider_user_id)
        if status:
            stmt = stmt.where(LogisticsRequest.status.in_(list(status)))
        if order_id:
            stmt = stmt.where(LogisticsRequest.order_id == order_id)
        if pickup_district:
            stmt = stmt.where(LogisticsRequest.pickup_district == pickup_district)
        if destination_district:
            stmt = stmt.where(LogisticsRequest.destination_district == destination_district)
        if user_id:
            stmt = stmt.join(Order, Order.id == LogisticsRequest.order_id).where(
                or_(Order.buyer_user_id == user_id, Order.seller_user_id == user_id)
            )
        return stmt

    def unassigned_count(self) -> int:
        return self.count(status=LogisticsStatus.REQUESTED, provider_user_id=None)


class LogisticsQuoteRepository(BaseRepository[LogisticsQuote]):
    def quotes_for_route(
        self, *, origin_district: str, destination_district: str, vehicle_type: str | None = None
    ) -> list[LogisticsQuote]:
        stmt = self._base_query().where(
            LogisticsQuote.origin_district == origin_district,
            LogisticsQuote.destination_district == destination_district,
            LogisticsQuote.is_active.is_(True),
        )
        if vehicle_type:
            stmt = stmt.where(LogisticsQuote.vehicle_type == vehicle_type)
        return list(self.session.execute(stmt).scalars().all())

    def quotes_for_origins(
        self, *, origin_district: str, destination_district: str
    ) -> list[LogisticsQuote]:
        return self.quotes_for_route(
            origin_district=origin_district, destination_district=destination_district
        )


class StorageRepository(BaseRepository[StorageFacility]):
    def search_query(
        self,
        *,
        owner_user_id: uuid.UUID | None = None,
        district: str | None = None,
        commodity_name: str | None = None,
        min_available_quintal: float | None = None,
        temperature_controlled: bool | None = None,
        include_private: bool = False,
        viewer_user_id: uuid.UUID | None = None,
    ) -> Select:
        """Search storage facilities.

        ``include_private`` only ever reveals a caller's **own** private
        facilities - never another owner's. Private godowns carry contact
        details, so widening this to "all private rows for anyone signed in"
        would leak phone numbers across tenants.
        """
        stmt = self._base_query()
        if owner_user_id:
            stmt = stmt.where(StorageFacility.owner_user_id == owner_user_id)
        if district:
            stmt = stmt.where(StorageFacility.district == district)
        if commodity_name:
            stmt = stmt.where(
                or_(
                    StorageFacility.supports_commodities.is_(None),
                    func.lower(func.coalesce(StorageFacility.supports_commodities, "")).like(
                        f"%{commodity_name.lower()}%"
                    ),
                )
            )
        if min_available_quintal:
            stmt = stmt.where(
                StorageFacility.capacity_quintal - StorageFacility.occupied_quintal
                >= min_available_quintal
            )
        if temperature_controlled is not None:
            stmt = stmt.where(StorageFacility.temperature_controlled == temperature_controlled)
        if include_private and viewer_user_id is not None:
            stmt = stmt.where(
                or_(
                    StorageFacility.is_private.is_(False),
                    StorageFacility.owner_user_id == viewer_user_id,
                )
            )
        else:
            stmt = stmt.where(StorageFacility.is_private.is_(False))
        return stmt.where(StorageFacility.is_active.is_(True)).order_by(
            StorageFacility.district, StorageFacility.name
        )

    def total_capacity(self) -> float:
        stmt = select(func.coalesce(func.sum(StorageFacility.capacity_quintal), 0.0)).where(
            StorageFacility.is_active.is_(True)
        )
        return float(self.session.execute(stmt).scalar_one() or 0.0)


class PaymentRepository(BaseRepository[Payment]):
    def _with_refs(self) -> Select:
        # Transaction has no ``commodity`` relationship, only a ``commodity_id``
        # column, and that is all the payment views read. Eager loading the order
        # is enough; asking for the missing relationship raised AttributeError
        # the moment a due-soon query ran.
        return self._base_query().options(
            joinedload(Payment.transaction).joinedload(Transaction.order),
        )

    def search_query(
        self,
        *,
        user_id: uuid.UUID | None = None,
        as_payer: bool | None = None,
        status: Sequence[PaymentStatus] | None = None,
        overdue_only: bool = False,
    ) -> Select:
        stmt = self._with_refs()
        if user_id:
            if as_payer is True:
                stmt = stmt.where(Payment.payer_user_id == user_id)
            elif as_payer is False:
                stmt = stmt.where(Payment.payee_user_id == user_id)
            else:
                stmt = stmt.where(
                    or_(Payment.payer_user_id == user_id, Payment.payee_user_id == user_id)
                )
        if status:
            stmt = stmt.where(Payment.status.in_(list(status)))
        if overdue_only:
            stmt = stmt.where(
                Payment.due_date < date.today(),
                Payment.status.in_([PaymentStatus.PENDING, PaymentStatus.PROCESSING]),
            )
        return stmt.order_by(Payment.due_date.asc().nulls_last(), Payment.created_at.desc())

    def due_soon_query(self, *, days: int = 7, user_id: uuid.UUID | None = None) -> Select:
        """Unsettled payments due within the next ``days`` days, soonest first.

        A real date window rather than a row cap, so widening ``days`` widens the
        window. Payments with no due date are excluded - they are not "due soon".
        """
        horizon = date.today() + timedelta(days=days)
        stmt = self._with_refs().where(
            Payment.status.in_([PaymentStatus.PENDING, PaymentStatus.PROCESSING]),
            Payment.due_date.isnot(None),
            Payment.due_date <= horizon,
        )
        if user_id is not None:
            stmt = stmt.where(
                or_(Payment.payer_user_id == user_id, Payment.payee_user_id == user_id)
            )
        return stmt.order_by(Payment.due_date.asc(), Payment.created_at.desc())

    def summary_for_user(self, user_id: uuid.UUID, *, as_payee: bool = True) -> dict[str, Any]:
        column = Payment.payee_user_id if as_payee else Payment.payer_user_id
        totals = select(
            func.coalesce(func.sum(Payment.amount), 0.0),
        ).where(column == user_id)
        expected = float(
            self.session.execute(totals.where(Payment.status != PaymentStatus.PAID)).scalar_one()
            or 0.0
        )
        paid = float(
            self.session.execute(totals.where(Payment.status == PaymentStatus.PAID)).scalar_one()
            or 0.0
        )
        overdue_stmt = select(
            func.coalesce(func.sum(Payment.amount), 0.0), func.count(Payment.id)
        ).where(
            column == user_id,
            Payment.due_date < date.today(),
            Payment.status.in_([PaymentStatus.PENDING, PaymentStatus.PROCESSING]),
        )
        overdue_amount, overdue_count = self.session.execute(overdue_stmt).one()
        by_status = (
            select(Payment.status, func.count(Payment.id))
            .where(column == user_id)
            .group_by(Payment.status)
        )
        return {
            "total_expected": round(expected, 2),
            "total_paid": round(paid, 2),
            "total_pending": round(expected, 2),
            "overdue_amount": round(float(overdue_amount or 0.0), 2),
            "overdue_count": int(overdue_count or 0),
            "by_status": {str(s): int(c) for s, c in self.session.execute(by_status).all()},
        }

    def platform_summary(self) -> dict[str, Any]:
        expected = float(
            self.session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                    Payment.status != PaymentStatus.PAID
                )
            ).scalar_one()
            or 0.0
        )
        paid = float(
            self.session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                    Payment.status == PaymentStatus.PAID
                )
            ).scalar_one()
            or 0.0
        )
        overdue_amount, overdue_count = self.session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0.0), func.count(Payment.id)).where(
                Payment.due_date < date.today(),
                Payment.status.in_([PaymentStatus.PENDING, PaymentStatus.PROCESSING]),
            )
        ).one()
        return {
            "total_expected": round(expected, 2),
            "total_paid": round(paid, 2),
            "total_pending": round(expected, 2),
            "overdue_amount": round(float(overdue_amount or 0.0), 2),
            "overdue_count": int(overdue_count or 0),
        }


class GrievanceRepository(BaseRepository[Grievance]):
    def _with_refs(self) -> Select:
        return self._base_query().options(
            joinedload(Grievance.raised_by),
            joinedload(Grievance.assigned_to),
            joinedload(Grievance.order),
            selectinload(Grievance.comments),
            selectinload(Grievance.evidence),
        )

    def get_detailed(self, grievance_id: uuid.UUID) -> Grievance | None:
        return (
            self.session.execute(self._with_refs().where(Grievance.id == grievance_id))
            .unique()
            .scalar_one_or_none()
        )

    def search_query(
        self,
        *,
        user_id: uuid.UUID | None = None,
        user_role: UserRole | None = None,
        status: Sequence[GrievanceStatus] | None = None,
        priority: Sequence[Priority] | None = None,
        assigned_to_user_id: uuid.UUID | None = None,
        category: str | None = None,
    ) -> Select:
        stmt = self._with_refs()
        if user_id and user_role not in (UserRole.ADMIN,):
            stmt = stmt.where(
                or_(Grievance.raised_by_user_id == user_id, Grievance.against_user_id == user_id)
            )
        if status:
            stmt = stmt.where(Grievance.status.in_(list(status)))
        if priority:
            stmt = stmt.where(Grievance.priority.in_(list(priority)))
        if assigned_to_user_id:
            stmt = stmt.where(Grievance.assigned_to_user_id == assigned_to_user_id)
        if category:
            stmt = stmt.where(Grievance.category == category)
        return stmt

    def counts_by_status(self) -> dict[str, int]:
        stmt = select(Grievance.status, func.count(Grievance.id)).group_by(Grievance.status)
        return {str(status): int(count) for status, count in self.session.execute(stmt).all()}

    def open_for_user(self, user_id: uuid.UUID) -> int:
        return int(
            self.session.execute(
                select(func.count(Grievance.id)).where(
                    Grievance.raised_by_user_id == user_id,
                    Grievance.status.in_([GrievanceStatus.OPEN, GrievanceStatus.UNDER_REVIEW]),
                )
            ).scalar_one()
        )


class QualityInspectionRepository(BaseRepository[QualityInspection]):
    def _with_refs(self) -> Select:
        return self._base_query().options(
            joinedload(QualityInspection.inspector),
            selectinload(QualityInspection.measurements).joinedload(QualityMeasurement.attribute),
        )

    def get_detailed(self, inspection_id: uuid.UUID) -> QualityInspection | None:
        return (
            self.session.execute(self._with_refs().where(QualityInspection.id == inspection_id))
            .unique()
            .scalar_one_or_none()
        )

    def search_query(
        self,
        *,
        lot_id: uuid.UUID | None = None,
        order_id: uuid.UUID | None = None,
        inspector_user_id: uuid.UUID | None = None,
        status: Sequence[InspectionStatus] | None = None,
        grade: Sequence[QualityGrade] | None = None,
    ) -> Select:
        stmt = self._with_refs()
        if lot_id is not None:
            stmt = stmt.where(QualityInspection.lot_id == lot_id)
        if order_id is not None:
            stmt = stmt.where(QualityInspection.order_id == order_id)
        if inspector_user_id is not None:
            stmt = stmt.where(QualityInspection.inspector_user_id == inspector_user_id)
        if status:
            stmt = stmt.where(QualityInspection.status.in_(list(status)))
        if grade:
            stmt = stmt.where(QualityInspection.grade.in_(list(grade)))
        return stmt.order_by(QualityInspection.created_at.desc())

    def for_lot(self, lot_id: uuid.UUID) -> list[QualityInspection]:
        return list(
            self.session.execute(
                self._with_refs()
                .where(QualityInspection.lot_id == lot_id)
                .order_by(QualityInspection.inspected_at.desc())
            )
            .unique()
            .scalars()
            .all()
        )

    def for_order(self, order_id: uuid.UUID) -> list[QualityInspection]:
        return list(
            self.session.execute(
                self._with_refs()
                .where(QualityInspection.order_id == order_id)
                .order_by(QualityInspection.inspected_at.desc())
            )
            .unique()
            .scalars()
            .all()
        )

    def pending_verification(self) -> list[QualityInspection]:
        from app.core.enums import InspectionStatus

        return list(
            self.session.execute(
                self._with_refs()
                .where(QualityInspection.status == InspectionStatus.PENDING)
                .order_by(QualityInspection.created_at.asc())
                .limit(50)
            )
            .unique()
            .scalars()
            .all()
        )

    def grade_distribution(self) -> list[tuple[str, int, float]]:
        """(grade, inspection_count, total quantity quintal) for analytics."""
        from app.models import FarmLot

        stmt = (
            select(
                QualityInspection.grade,
                func.count(QualityInspection.id),
                func.coalesce(func.sum(FarmLot.quantity), 0.0),
            )
            .select_from(QualityInspection)
            .outerjoin(FarmLot, FarmLot.id == QualityInspection.lot_id)
            .group_by(QualityInspection.grade)
        )
        return [
            (str(grade), int(count), float(quantity or 0))
            for grade, count, quantity in self.session.execute(stmt).all()
        ]


class AuditRepository(BaseRepository[AuditLog]):
    def search(
        self,
        *,
        actor_user_id: uuid.UUID | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        request_id: str | None = None,
        from_date: datetime | None = None,
    ) -> Select:
        stmt = self._base_query().options(joinedload(AuditLog.actor))
        if actor_user_id:
            stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if entity_type:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if request_id:
            stmt = stmt.where(AuditLog.request_id == request_id)
        if from_date:
            stmt = stmt.where(AuditLog.created_at >= from_date)
        return stmt.order_by(AuditLog.created_at.desc())

    def entity_history(self, entity_type: str, entity_id: str) -> list[AuditLog]:
        return self.find_all(
            filters={"entity_type": entity_type, "entity_id": entity_id},
            order_by=["-created_at"],
            limit=200,
        )
