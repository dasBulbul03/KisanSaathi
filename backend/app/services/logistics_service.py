"""Logistics service backed by a pluggable LogisticsProvider."""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import (
    LogisticsStatus,
    NotificationType,
    OrderStatus,
    UserRole,
    VehicleType,
)
from app.core.exceptions import (
    InvalidStateTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.logging import get_logger
from app.models import (
    LogisticsQuote,
    LogisticsRequest,
    Order,
    User,
)
from app.repositories.operations import LogisticsQuoteRepository, LogisticsRepository
from app.repositories.trade import OrderRepository
from app.schemas.operations import LogisticsCreate, LogisticsUpdate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.codes import logistics_reference
from app.utils.geo import distance_between
from app.utils.units import convert_quantity, normalise_unit

logger = get_logger(__name__)

LOGISTICS_TRANSITIONS: dict[LogisticsStatus, set[LogisticsStatus]] = {
    LogisticsStatus.REQUESTED: {LogisticsStatus.ASSIGNED, LogisticsStatus.CANCELLED},
    LogisticsStatus.ASSIGNED: {LogisticsStatus.PICKUP_SCHEDULED, LogisticsStatus.CANCELLED},
    LogisticsStatus.PICKUP_SCHEDULED: {LogisticsStatus.IN_TRANSIT, LogisticsStatus.CANCELLED},
    LogisticsStatus.IN_TRANSIT: {LogisticsStatus.DELIVERED, LogisticsStatus.CANCELLED},
    LogisticsStatus.DELIVERED: set(),
    LogisticsStatus.CANCELLED: set(),
}

VEHICLE_CAPACITY_QUINTAL: dict[VehicleType, float] = {
    VehicleType.TEMPO: 60.0,
    VehicleType.MINI_TRUCK: 100.0,
    VehicleType.TRUCK_10FT: 180.0,
    VehicleType.TRUCK_14FT: 280.0,
    VehicleType.TRUCK_17FT: 400.0,
    VehicleType.REFRIGERATED: 150.0,
}


@dataclass
class LogisticsOption:
    provider_name: str
    vehicle_type: VehicleType
    distance_km: float
    estimated_cost: float
    transit_days: int
    rating: float
    is_demo: bool
    note: str | None = None


class LogisticsProvider:
    """Interface for external transport providers (aggregators, fleet APIs)."""

    name = "abstract"

    def get_quotes(
        self,
        *,
        origin_district: str,
        destination_district: str,
        quantity_quintal: float,
        cold_chain_required: bool = False,
        session: Session | None = None,
    ) -> list[LogisticsOption]:
        raise NotImplementedError

    def assign(self, request: LogisticsRequest) -> LogisticsRequest:
        raise NotImplementedError

    def track(self, request: LogisticsRequest) -> dict[str, Any]:
        raise NotImplementedError


class DemoLogisticsProvider(LogisticsProvider):
    """Rate-card based quotes served from the ``logistics_quotes`` table."""

    name = "demo"

    #: Fallback rates (Rs per quintal per km) when no rate card row exists.
    DEFAULT_PER_KM = 3.2
    DEFAULT_BASE = 450.0
    LOADING_PER_QUINTAL = 1.1

    def get_quotes(
        self,
        *,
        origin_district: str,
        destination_district: str,
        quantity_quintal: float,
        cold_chain_required: bool = False,
        session: Session | None = None,
    ) -> list[LogisticsOption]:
        if session is None:
            return self._fallback_quotes(
                origin_district, destination_district, quantity_quintal, cold_chain_required
            )
        repo = LogisticsQuoteRepository(LogisticsQuote, session)
        quotes = repo.quotes_for_route(
            origin_district=origin_district, destination_district=destination_district
        )
        if not quotes:
            quotes = repo.find_all(
                filters={"origin_district": origin_district, "is_active": True}, limit=20
            )
        distance = self._distance(origin_district, destination_district)
        options: list[LogisticsOption] = []
        for quote in quotes:
            cost = self._cost(
                base=quote.base_rate,
                per_km=quote.per_km_rate,
                per_quintal=quote.per_quintal_rate,
                distance=distance,
                quantity=quantity_quintal,
                min_charge=quote.min_charge,
                cold_chain=cold_chain_required,
                cold_surcharge=quote.cold_chain_surcharge,
            )
            options.append(
                LogisticsOption(
                    provider_name=quote.provider_name,
                    vehicle_type=quote.vehicle_type,
                    distance_km=distance,
                    estimated_cost=cost,
                    transit_days=max(1, quote.transit_days + (1 if cold_chain_required else 0)),
                    rating=quote.rating,
                    is_demo=quote.is_demo,
                    note=(
                        f"Rate card valid {quote.min_distance_km:,.0f}–"
                        f"{quote.max_distance_km:,.0f} km"
                    ),
                )
            )
        options.sort(key=lambda o: o.estimated_cost)
        return options[:5] or self._fallback_quotes(
            origin_district, destination_district, quantity_quintal, cold_chain_required
        )

    def _fallback_quotes(
        self,
        origin_district: str,
        destination_district: str,
        quantity_quintal: float,
        cold_chain_required: bool,
    ) -> list[LogisticsOption]:
        distance = self._distance(origin_district, destination_district)
        options: list[LogisticsOption] = []
        for vehicle, capacity in VEHICLE_CAPACITY_QUINTAL.items():
            if vehicle is VehicleType.REFRIGERATED and not cold_chain_required:
                continue
            if quantity_quintal > capacity * 6 and vehicle is VehicleType.TEMPO:
                continue
            cost = self._cost(
                base=self.DEFAULT_BASE,
                per_km=self.DEFAULT_PER_KM,
                per_quintal=self.LOADING_PER_QUINTAL,
                distance=distance,
                quantity=quantity_quintal,
                min_charge=0.0,
                cold_chain=cold_chain_required,
                cold_surcharge=150.0,
            )
            options.append(
                LogisticsOption(
                    provider_name="KisanSaathi Transport Desk (demo rates)",
                    vehicle_type=vehicle,
                    distance_km=distance,
                    estimated_cost=cost,
                    transit_days=max(1, int(math.ceil(distance / 250)) + 1),
                    rating=4.1,
                    is_demo=True,
                    note="Indicative rate card - not a booked transporter",
                )
            )
        options.sort(key=lambda o: o.estimated_cost)
        return options[:4]

    @staticmethod
    def _cost(
        *,
        base: float,
        per_km: float,
        per_quintal: float,
        distance: float,
        quantity: float,
        min_charge: float,
        cold_chain: bool,
        cold_surcharge: float,
    ) -> float:
        cost = base + distance * per_km + quantity * per_quintal
        if cold_chain:
            cost += cold_surcharge
        return round(max(cost, min_charge), 2)

    @staticmethod
    def _distance(origin: str, destination: str) -> float:
        from app.utils.geo import district_coords, haversine_km

        o_lat, o_lon = district_coords(origin)
        d_lat, d_lon = district_coords(destination)
        if None in (o_lat, o_lon, d_lat, d_lon):
            return 150.0 if origin != destination else 25.0
        return haversine_km(o_lat or 0, o_lon or 0, d_lat or 0, d_lon or 0)


class LogisticsService:
    def __init__(self, session: Session, provider: LogisticsProvider | None = None) -> None:
        self.session = session
        self.requests = LogisticsRepository(LogisticsRequest, session)
        self.orders = OrderRepository(Order, session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)
        self.provider = provider or DemoLogisticsProvider()

    # ------------------------------------------------------------- helpers
    def get_request(self, request_id: uuid.UUID) -> LogisticsRequest:
        request = self.requests.get_detailed(request_id)
        if request is None:
            raise NotFoundError(
                "The logistics request could not be found.", code="LOGISTICS_NOT_FOUND"
            )
        return request

    def get_for_order(self, order_id: uuid.UUID) -> LogisticsRequest | None:
        return self.requests.for_order(order_id)

    def quote_options(
        self,
        *,
        origin_district: str,
        destination_district: str,
        quantity: float,
        unit: str = "quintal",
        cold_chain_required: bool = False,
    ) -> list[LogisticsOption]:
        quantity_quintal = convert_quantity(quantity, unit, "quintal")
        return self.provider.get_quotes(
            origin_district=origin_district,
            destination_district=destination_district,
            quantity_quintal=quantity_quintal,
            cold_chain_required=cold_chain_required,
            session=self.session,
        )

    def estimate_for_order(self, order: Order) -> list[LogisticsOption]:
        quantity = convert_quantity(order.quantity, order.unit, "quintal")
        return self.provider.get_quotes(
            origin_district=order.pickup_district or "Pune",
            destination_district=order.delivery_district or order.pickup_district or "Pune",
            quantity_quintal=quantity,
            cold_chain_required=bool(order.commodity and order.commodity.is_perishable),
            session=self.session,
        )

    # ----------------------------------------------------------- mutations
    def create_request(self, payload: LogisticsCreate, user: User) -> LogisticsRequest:
        order = self.orders.get_detailed(payload.order_id)
        if order is None:
            raise NotFoundError("The order could not be found.", code="ORDER_NOT_FOUND")
        if user.id not in (order.buyer_user_id, order.seller_user_id) and user.role not in (
            UserRole.ADMIN,
            UserRole.LOGISTICS_PARTNER,
        ):
            raise PermissionDeniedError(
                "You do not have access to this order.", code="ORDER_FORBIDDEN"
            )
        if self.get_for_order(order.id) is not None:
            from app.core.exceptions import ConflictError

            raise ConflictError(
                "A logistics request already exists for this order.", code="LOGISTICS_EXISTS"
            )
        if order.status not in (
            OrderStatus.ORDER_CREATED,
            OrderStatus.LOGISTICS_ASSIGNED,
        ):
            raise InvalidStateTransitionError(
                f"Logistics cannot be arranged while the order is "
                f"{order.status.value.lower()}.",
                code="LOGISTICS_NOT_ALLOWED",
            )
        distance = distance_between(
            None,
            None,
            None,
            None,
            order.pickup_district,
            order.delivery_district,
        )
        estimated = payload.estimated_cost
        if estimated is None:
            options = self.estimate_for_order(order)
            estimated = options[0].estimated_cost if options else None
        request = LogisticsRequest(
            reference_code=logistics_reference(),
            order_id=order.id,
            provider_user_id=payload.provider_user_id,
            status=(
                LogisticsStatus.ASSIGNED if payload.provider_user_id else LogisticsStatus.REQUESTED
            ),
            pickup_location=order.pickup_location,
            pickup_district=order.pickup_district,
            destination=order.delivery_location,
            destination_district=order.delivery_district,
            distance_km=distance.km,
            quantity=order.quantity,
            unit=order.unit,
            vehicle_type=payload.vehicle_type,
            estimated_cost=estimated,
            transporter_name=payload.transporter_name,
            transporter_contact=payload.transporter_contact,
            pickup_date=payload.pickup_date or order.pickup_date,
            delivery_date=payload.delivery_date or order.delivery_date,
            cold_chain_required=payload.cold_chain_required,
            notes=payload.notes,
            status_history=[
                {
                    "status": (
                        LogisticsStatus.ASSIGNED.value
                        if payload.provider_user_id
                        else LogisticsStatus.REQUESTED.value
                    ),
                    "at": datetime.now(UTC).isoformat(),
                    "by": str(user.id),
                }
            ],
        )
        self.session.add(request)
        self.session.flush()
        self.audit.record(
            action="LOGISTICS_REQUESTED",
            entity_type="logistics_request",
            entity_id=request.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={
                "reference_code": request.reference_code,
                "order_id": str(order.id),
                "estimated_cost": request.estimated_cost,
            },
        )
        if payload.provider_user_id:
            self.notifications.notify(
                payload.provider_user_id,
                notification_type=NotificationType.LOGISTICS_UPDATE,
                title=f"New pickup job {request.reference_code}",
                body=(
                    f"Collect {order.quantity:,.0f} {normalise_unit(order.unit)} from "
                    f"{order.pickup_location} for {order.delivery_location}."
                ),
                link="/logistics",
            )
        if order.status is OrderStatus.ORDER_CREATED:
            from app.services.order_service import OrderService

            OrderService(self.session).update_status(
                order.id,
                _status_payload(order, OrderStatus.LOGISTICS_ASSIGNED, request),
                user,
            )
        return self.get_request(request.id)

    def assign(
        self, request_id: uuid.UUID, provider_user_id: uuid.UUID, user: User
    ) -> LogisticsRequest:
        request = self.get_request(request_id)
        if user.role not in (UserRole.ADMIN, UserRole.LOGISTICS_PARTNER):
            raise PermissionDeniedError(
                "Only administrators and logistics partners can accept a job.",
                code="LOGISTICS_ASSIGN_FORBIDDEN",
            )
        if request.status is not LogisticsStatus.REQUESTED:
            raise InvalidStateTransitionError(
                "This job has already been assigned or closed.", code="LOGISTICS_ALREADY_ASSIGNED"
            )
        request.provider_user_id = provider_user_id
        request.status = LogisticsStatus.ASSIGNED
        request.status_history = list(request.status_history or []) + [
            {
                "status": LogisticsStatus.ASSIGNED.value,
                "at": datetime.now(UTC).isoformat(),
                "by": str(user.id),
            }
        ]
        self.session.flush()
        self.audit.record(
            action="LOGISTICS_ASSIGNED",
            entity_type="logistics_request",
            entity_id=request.id,
            actor_user_id=user.id,
            actor_role=user.role,
            after={"provider_user_id": str(provider_user_id)},
        )
        order = request.order
        if order and order.status is OrderStatus.ORDER_CREATED:
            from app.services.order_service import OrderService

            OrderService(self.session).update_status(
                order.id,
                _status_payload(order, OrderStatus.LOGISTICS_ASSIGNED, request),
                user,
            )
        return self.get_request(request_id)

    def update(
        self, request_id: uuid.UUID, payload: LogisticsUpdate, user: User
    ) -> LogisticsRequest:
        request = self.get_request(request_id)
        is_owner_partner = request.provider_user_id == user.id
        if not (is_owner_partner or user.role is UserRole.ADMIN):
            raise PermissionDeniedError(
                "Only the assigned transporter or an administrator can update this job.",
                code="LOGISTICS_UPDATE_FORBIDDEN",
            )
        if payload.status is not None and payload.status is not request.status:
            allowed = LOGISTICS_TRANSITIONS.get(request.status, set())
            if payload.status not in allowed:
                raise InvalidStateTransitionError(
                    f"A {request.status.value.lower()} job cannot move to "
                    f"{payload.status.value.lower()}.",
                    code="LOGISTICS_INVALID_TRANSITION",
                )
        data = payload.model_dump(exclude_unset=True)
        new_status = data.pop("status", None)
        before = {"status": request.status.value}
        for key, value in data.items():
            if value is not None and hasattr(request, key):
                setattr(request, key, value)
        if new_status is not None:
            request.status = new_status
            if new_status is LogisticsStatus.PICKUP_SCHEDULED:
                request.pickup_date = request.pickup_date or date.today()
            if new_status is LogisticsStatus.IN_TRANSIT:
                request.pickup_actual_at = datetime.now(UTC)
            if new_status is LogisticsStatus.DELIVERED:
                request.delivery_actual_at = datetime.now(UTC)
        if new_status is not None:
            request.status_history = list(request.status_history or []) + [
                {
                    "status": new_status.value,
                    "at": datetime.now(UTC).isoformat(),
                    "by": str(user.id),
                    "by_name": user.full_name,
                }
            ]
        self.session.flush()
        self.audit.record(
            action="LOGISTICS_UPDATED",
            entity_type="logistics_request",
            entity_id=request.id,
            actor_user_id=user.id,
            actor_role=user.role,
            before=before,
            after={"status": request.status.value},
        )
        order = request.order
        if order is not None and new_status is not None:
            target = {
                LogisticsStatus.PICKUP_SCHEDULED: OrderStatus.PICKUP_SCHEDULED,
                LogisticsStatus.IN_TRANSIT: OrderStatus.IN_TRANSIT,
                LogisticsStatus.DELIVERED: OrderStatus.DELIVERED,
            }.get(new_status)
            if target:
                from app.services.order_service import OrderService

                service = OrderService(self.session)
                if service.can_transition(order, target, user):
                    service.update_status(
                        order.id,
                        _status_payload(order, target, request),
                        user,
                    )
        return self.get_request(request_id)

    def cancel(
        self, request_id: uuid.UUID, user: User, *, reason: str | None = None
    ) -> LogisticsRequest:
        request = self.get_request(request_id)
        if user.role is not UserRole.ADMIN and request.provider_user_id != user.id:
            order = request.order
            if order is None or user.id not in (order.buyer_user_id, order.seller_user_id):
                raise PermissionDeniedError(
                    "You do not have access to this logistics job.",
                    code="LOGISTICS_CANCEL_FORBIDDEN",
                )
        if LogisticsStatus.CANCELLED not in LOGISTICS_TRANSITIONS.get(request.status, set()):
            raise InvalidStateTransitionError(
                "This job can no longer be cancelled.", code="LOGISTICS_NOT_CANCELLABLE"
            )
        request.status = LogisticsStatus.CANCELLED
        request.status_history = list(request.status_history or []) + [
            {
                "status": LogisticsStatus.CANCELLED.value,
                "at": datetime.now(UTC).isoformat(),
                "by": str(user.id),
                "note": reason,
            }
        ]
        self.session.flush()
        self.audit.record(
            action="LOGISTICS_CANCELLED",
            entity_type="logistics_request",
            entity_id=request.id,
            actor_user_id=user.id,
            actor_role=user.role,
            note=reason,
        )
        return self.get_request(request_id)

    # ------------------------------------------------------------- queries
    def list_requests(
        self,
        *,
        user: User,
        role_view: str = "all",
        provider_user_id: uuid.UUID | None = None,
        status: Sequence[LogisticsStatus] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[LogisticsRequest], int]:
        if role_view == "provider":
            stmt = self.requests.search_query(
                provider_user_id=provider_user_id or user.id, status=status
            )
        elif role_view == "mine":
            stmt = self.requests.search_query(user_id=user.id, status=status)
        elif user.role is UserRole.LOGISTICS_PARTNER:
            stmt = self.requests.search_query(
                provider_user_id=provider_user_id or user.id, status=status
            )
        elif user.role is UserRole.ADMIN:
            stmt = self.requests.search_query(provider_user_id=provider_user_id, status=status)
        else:
            stmt = self.requests.search_query(user_id=user.id, status=status)
        stmt = stmt.order_by(LogisticsRequest.created_at.desc())
        return self.requests.paginate(stmt=stmt, page=page, page_size=page_size)

    def enrich(self, request: LogisticsRequest) -> dict[str, Any]:
        order = request.order
        return {
            "id": request.id,
            "reference_code": request.reference_code,
            "order_id": request.order_id,
            "order_number": order.order_number if order else None,
            "commodity_name": order.commodity.name if order and order.commodity else None,
            "provider_user_id": request.provider_user_id,
            "provider_name": request.provider.full_name if request.provider else None,
            "status": request.status,
            "pickup_location": request.pickup_location,
            "pickup_district": request.pickup_district,
            "destination": request.destination,
            "destination_district": request.destination_district,
            "distance_km": request.distance_km,
            "quantity": request.quantity,
            "unit": request.unit,
            "vehicle_type": request.vehicle_type,
            "vehicle_number": request.vehicle_number,
            "estimated_cost": request.estimated_cost,
            "actual_cost": request.actual_cost,
            "transporter_name": request.transporter_name,
            "transporter_contact": request.transporter_contact,
            "pickup_date": request.pickup_date,
            "delivery_date": request.delivery_date,
            "tracking_number": request.tracking_number,
            "cold_chain_required": request.cold_chain_required,
            "status_history": request.status_history or [],
            "created_at": request.created_at,
            "updated_at": request.updated_at,
        }


def _status_payload(order: Order, status: OrderStatus, request: LogisticsRequest):
    from app.schemas.trade import OrderStatusUpdate

    return OrderStatusUpdate(
        status=status,
        note=f"Logistics job {request.reference_code} updated",
        pickup_date=request.pickup_date,
        delivery_date=request.delivery_date,
    )
