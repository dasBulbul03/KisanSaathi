"""Role-aware dashboard assembly.

The three dashboard payloads (``FarmerDashboard``, ``BuyerDashboard``,
``AdminDashboard``) are intentionally assembled from plain dicts rather than a
generic analytics framework: each surface answers a specific question, and the
stats a farmer sees are deliberately different from those an admin sees.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.enums import GrievanceStatus, OrderStatus, PriceSource, UserRole
from app.core.exceptions import PermissionDeniedError
from app.core.logging import get_logger
from app.models import (
    AIRecommendation,
    AuditLog,
    BuyerDemand,
    Commodity,
    FarmLot,
    Grievance,
    LogisticsRequest,
    MarketPrice,
    Offer,
    Order,
    Payment,
    QualityInspection,
    Transaction,
    User,
)
from app.repositories.ai import RecommendationRepository
from app.repositories.markets import MarketPriceRepository
from app.repositories.operations import (
    AuditRepository,
    GrievanceRepository,
    LogisticsRepository,
    PaymentRepository,
    QualityInspectionRepository,
)
from app.repositories.trade import (
    DemandRepository,
    LotRepository,
    OfferRepository,
    OrderRepository,
    TransactionRepository,
)
from app.repositories.users import UserRepository
from app.schemas.ai import (
    AdminDashboard,
    BuyerDashboard,
    DashboardStat,
    FarmerDashboard,
    MarketInsightCard,
)
from app.services.demand_service import DemandService
from app.services.lot_service import LotService
from app.services.market_service import MarketService
from app.services.matching_service import MatchingService
from app.services.notification_service import NotificationService
from app.services.offer_service import OfferService
from app.services.order_service import OrderService

logger = get_logger(__name__)

ACTIVE_LOT_STATUSES = ("PUBLISHED", "UNDER_OFFER")
OPEN_DEMAND_STATUSES = ("OPEN", "PARTIALLY_FULFILLED")
OPEN_GRIEVANCE_STATUSES = (
    GrievanceStatus.OPEN,
    GrievanceStatus.UNDER_REVIEW,
    GrievanceStatus.ESCALATED,
)
PENDING_ORDER_STATUSES = tuple(s for s in OrderStatus if s is not OrderStatus.COMPLETED)


def _stat(
    label: str,
    value: float,
    *,
    unit: str | None = None,
    display: str | None = None,
    change_pct: float | None = None,
    trend: str | None = None,
    hint: str | None = None,
) -> DashboardStat:
    return DashboardStat(
        label=label,
        value=round(float(value), 2),
        display=display if display is not None else f"{value:,.0f}",
        unit=unit,
        change_pct=change_pct,
        trend=trend,
        hint=hint,
    )


def _greeting(user: User) -> str:
    hour = datetime.now(UTC).hour
    part = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    first_name = (user.full_name or "").split(" ")[0] or "there"
    return f"{part}, {first_name}"


class DashboardService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(User, session)
        self.lots_repo = LotRepository(FarmLot, session)
        self.demands_repo = DemandRepository(BuyerDemand, session)
        self.offers_repo = OfferRepository(Offer, session)
        self.orders_repo = OrderRepository(Order, session)
        self.transactions = TransactionRepository(Transaction, session)
        self.payments = PaymentRepository(Payment, session)
        self.grievances = GrievanceRepository(Grievance, session)
        self.inspections = QualityInspectionRepository(QualityInspection, session)
        self.logistics = LogisticsRepository(LogisticsRequest, session)
        self.prices = MarketPriceRepository(MarketPrice, session)
        self.audit = AuditRepository(AuditLog, session)
        self.recommendations = RecommendationRepository(AIRecommendation, session)

    # ------------------------------------------------------------- shared
    def _prices_are_synthetic(self) -> bool:
        """True when the price history on screen came from the demo provider.

        Read from the stored ``source`` rather than from configuration, so a
        database that was partly synced from a real API is not mislabelled. If
        every recorded row is ``DEMO`` the figures are synthetic and the UI says
        so; a single real source means the history is real and the flag is off.
        """
        sources = {row[0] for row in self.session.query(MarketPrice.source).distinct().all()}
        if not sources:
            return False
        return sources <= {PriceSource.DEMO.value}

    def _origin(self, user: User) -> tuple[str | None, float | None, float | None]:
        district = user.district
        latitude = longitude = None
        profile = user.farmer_profile or user.fpo_profile or user.buyer_profile
        if profile is not None:
            latitude = getattr(profile, "latitude", None)
            longitude = getattr(profile, "longitude", None)
            district = district or getattr(profile, "district", None)
        return district, latitude, longitude

    def _price_cards(self, user: User, limit: int = 4) -> list[dict[str, Any]]:
        """Mandí rate cards for the crops this user actually trades in."""
        market = MarketService(self.session)
        district, latitude, longitude = self._origin(user)
        rows = (
            self.session.query(FarmLot.commodity_id, func.count(FarmLot.id).label("n"))
            .filter(FarmLot.seller_user_id == user.id)
            .group_by(FarmLot.commodity_id)
            .order_by(func.count(FarmLot.id).desc())
            .limit(limit)
            .all()
        )
        if not rows:
            # No lots yet: fall back to a general view of the catalogue, reshaped
            # into the same card contract. _insights() reads commodity_name and
            # modal_price, and the overview calls them commodity and
            # median_modal_price, so returning it raw would 500 the dashboard.
            return [
                {
                    "commodity_id": card["commodity_id"],
                    "commodity_name": card["commodity"],
                    "unit": card["unit"],
                    "modal_price": card["median_modal_price"],
                    "min_price": card["min_modal"],
                    "max_price": card["max_modal"],
                    "price_date": None,
                    "arrivals_quintal": None,
                    "change_pct_7d": card["change_pct_7d"],
                    "trend": "up"
                    if (card["change_pct_7d"] or 0) > 0.5
                    else "down"
                    if (card["change_pct_7d"] or 0) < -0.5
                    else "flat",
                    "my_lots": 0,
                }
                for card in market.commodity_price_overview(limit=limit)
            ]
        cards: list[dict[str, Any]] = []
        for commodity_id, lot_count in rows:
            commodity = self.session.get(Commodity, commodity_id)
            if commodity is None:
                continue
            try:
                snapshot = market.price_snapshot(
                    commodity_id,
                    district=district,
                    origin_latitude=latitude,
                    origin_longitude=longitude,
                )
                trend = market.trend(commodity_id, days=7, district=district)
            except Exception as exc:  # a single bad commodity must not 500 the page
                logger.warning(
                    "dashboard.price_card.failed", commodity=commodity_id, error=str(exc)
                )
                continue
            change = trend.overall_change_pct
            cards.append(
                {
                    "commodity_id": str(commodity_id),
                    "commodity_name": commodity.name,
                    "unit": commodity.default_unit,
                    "modal_price": snapshot.get("modal_price"),
                    "min_price": snapshot.get("min_price"),
                    "max_price": snapshot.get("max_price"),
                    "price_date": snapshot.get("price_date"),
                    "arrivals_quintal": snapshot.get("arrivals_quantity"),
                    "change_pct_7d": change,
                    "trend": "up"
                    if (change or 0) > 0.5
                    else "down"
                    if (change or 0) < -0.5
                    else "flat",
                    "my_lots": lot_count,
                }
            )
        return cards

    def _notification_cards(self, user: User, limit: int = 5) -> list[dict[str, Any]]:
        items, _ = NotificationService(self.session).list_for_user(user.id)
        return [
            {
                "id": str(n.id),
                "title": n.title,
                "body": n.body,
                "type": n.notification_type.value
                if hasattr(n.notification_type, "value")
                else str(n.notification_type),
                "is_read": n.is_read,
                "link": n.link,
                "created_at": n.created_at.isoformat(),
            }
            for n in items[:limit]
        ]

    def _insights(self, user: User, cards: list[dict[str, Any]]) -> list[MarketInsightCard]:
        """Rule-based insight cards - each one must be actionable."""
        insights: list[MarketInsightCard] = []
        rising = [c for c in cards if (c.get("change_pct_7d") or 0) > 3]
        falling = [c for c in cards if (c.get("change_pct_7d") or 0) < -3]
        if rising:
            top = max(rising, key=lambda c: c["change_pct_7d"])
            insights.append(
                MarketInsightCard(
                    kind="price_up",
                    title=f"{top['commodity_name']} is trending up",
                    message=(
                        f"Up {top['change_pct_7d']:,.1f}% in 7 days to about "
                        f"{float(top['modal_price'] or 0):,.0f} per {top['unit']}. "
                        "Consider releasing your stock now or asking a slightly higher price."
                    ),
                    tone="positive",
                    action_label="Review price advice",
                    action_href=f"/market/price-discovery?commodity={top['commodity_id']}",
                )
            )
        if falling:
            worst = min(falling, key=lambda c: c["change_pct_7d"])
            insights.append(
                MarketInsightCard(
                    kind="price_down",
                    title=f"{worst['commodity_name']} has softened",
                    message=(
                        f"Down {abs(worst['change_pct_7d']):,.1f}% in 7 days. Heavy arrivals "
                        "are likely; check whether storage costs less than the expected "
                        "further decline."
                    ),
                    tone="warning",
                    action_label="Check storage options",
                    action_href="/storage",
                )
            )
        draft = (
            self.session.query(func.count(FarmLot.id))
            .filter(FarmLot.seller_user_id == user.id, FarmLot.status == "DRAFT")
            .scalar()
            or 0
        )
        if draft:
            insights.append(
                MarketInsightCard(
                    kind="action",
                    title=f"{draft} lot(s) still in draft",
                    message=(
                        "Draft lots are invisible to buyers. Publish them to start "
                        "receiving offers."
                    ),
                    tone="info",
                    action_label="Publish lots",
                    action_href="/my-lots?status=DRAFT",
                )
            )
        pending = (
            self.session.query(func.count(Offer.id))
            .join(FarmLot, Offer.lot_id == FarmLot.id)
            .filter(
                FarmLot.seller_user_id == user.id,
                Offer.status == "PENDING",
            )
            .scalar()
            or 0
        )
        if pending:
            insights.append(
                MarketInsightCard(
                    kind="action",
                    title=f"{pending} offer(s) waiting on you",
                    message=(
                        "Buyers are waiting on a response. Accepting moves the order to "
                        "fulfilment."
                    ),
                    tone="info",
                    action_label="Review offers",
                    action_href="/offers?status=PENDING",
                )
            )
        if not insights:
            insights.append(
                MarketInsightCard(
                    kind="empty",
                    title="Nothing needs your attention",
                    message=(
                        "No price alerts or pending actions right now. Publish a lot to "
                        "get started."
                    ),
                    tone="info",
                    action_label="Create a lot",
                    action_href="/lots/new",
                )
            )
        return insights

    def _latest_recommendation(self, user: User) -> dict[str, Any] | None:
        latest: AIRecommendation | None = (
            self.session.query(AIRecommendation)
            .filter(AIRecommendation.user_id == user.id)
            .order_by(AIRecommendation.created_at.desc())
            .first()
        )
        if latest is None:
            return None
        return {
            "id": str(latest.id),
            "kind": latest.kind,
            "title": latest.title,
            "summary": latest.summary,
            "confidence": latest.confidence.value
            if hasattr(latest.confidence, "value")
            else str(latest.confidence),
            "engine": latest.engine,
            "generated_at": latest.created_at.isoformat(),
        }

    # ------------------------------------------------------------- farmer
    def farmer_dashboard(self, user: User) -> FarmerDashboard:
        lots_service = LotService(self.session)
        offers_service = OfferService(self.session)
        orders_service = OrderService(self.session)

        status_counts = lots_service.status_counts(user.id)
        active_lots = sum(status_counts.get(s, 0) for s in ACTIVE_LOT_STATUSES)
        listed_quintal = (
            self.session.query(func.coalesce(func.sum(FarmLot.available_quantity), 0.0))
            .filter(
                FarmLot.seller_user_id == user.id,
                FarmLot.status.in_(ACTIVE_LOT_STATUSES),
            )
            .scalar()
            or 0.0
        )
        pending_offers = (
            self.session.query(func.count(Offer.id))
            .join(FarmLot, Offer.lot_id == FarmLot.id)
            .filter(FarmLot.seller_user_id == user.id, Offer.status == "PENDING")
            .scalar()
            or 0
        )
        pipeline = orders_service.pipeline(user.id, user_role=user.role)
        open_value = sum(
            float(row["value"]) for row in pipeline if row["status"] != OrderStatus.COMPLETED.value
        )
        matches = MatchingService(self.session).matches_for_user(
            user.id, role=user.role.value, limit=5
        )
        price_cards = self._price_cards(user)
        seller: dict[str, Any] = {
            "id": str(user.id),
            "full_name": user.full_name,
            "role": user.role.value,
            "district": user.district,
            "village": getattr(user.farmer_profile, "village", None)
            if user.farmer_profile
            else None,
            "organisation_name": getattr(user.fpo_profile, "organisation_name", None)
            if user.fpo_profile
            else None,
            "farmer_id_code": getattr(user.farmer_profile, "farmer_id_code", None)
            if user.farmer_profile
            else None,
            "primary_crops": list(getattr(user.farmer_profile, "primary_crops", None) or [])
            if user.farmer_profile
            else [],
        }
        lots, _ = lots_service.list_lots(seller_user_id=user.id, page=1, page_size=5)
        offers, _ = offers_service.list_offers(user=user, role_view="incoming", page=1, page_size=5)
        return FarmerDashboard(
            generated_at=datetime.now(UTC),
            greeting=_greeting(user),
            seller=seller,
            stats=[
                _stat("Active lots", active_lots, hint="Published or under offer"),
                _stat("Quantity listed", listed_quintal, unit="quintal"),
                _stat("Offers to review", pending_offers, hint="Waiting for your response"),
                _stat("Open trade value", open_value, unit="INR", display=f"₹{open_value:,.0f}"),
                _stat("Matching buyers", len(matches), hint="Based on your active lots"),
            ],
            price_cards=price_cards,
            insights=self._insights(user, price_cards),
            active_lots=[lots_service.enrich(lot) for lot in lots],
            recent_offers=[offers_service.enrich(offer, viewer=user) for offer in offers],
            order_pipeline=pipeline,
            notifications=self._notification_cards(user),
            ai_recommendation=self._latest_recommendation(user),
            is_demo_data=self._prices_are_synthetic(),
        )

    # -------------------------------------------------------------- buyer
    def buyer_dashboard(self, user: User) -> BuyerDashboard:
        demands_service = DemandService(self.session)
        orders_service = OrderService(self.session)
        offers_service = OfferService(self.session)

        open_demands = (
            self.session.query(func.count(BuyerDemand.id))
            .filter(
                BuyerDemand.buyer_user_id == user.id, BuyerDemand.status.in_(OPEN_DEMAND_STATUSES)
            )
            .scalar()
            or 0
        )
        open_value = (
            self.session.query(func.coalesce(func.sum(BuyerDemand.required_quantity), 0.0))
            .filter(
                BuyerDemand.buyer_user_id == user.id, BuyerDemand.status.in_(OPEN_DEMAND_STATUSES)
            )
            .scalar()
            or 0.0
        )
        pending_offers = (
            self.session.query(func.count(Offer.id))
            .filter(Offer.buyer_user_id == user.id, Offer.status == "PENDING")
            .scalar()
            or 0
        )
        outstanding = self.payments.summary_for_user(user.id, as_payee=False)
        matches = MatchingService(self.session).matches_for_user(
            user.id, role=user.role.value, limit=5
        )

        buyer: dict[str, Any] = {
            "id": str(user.id),
            "full_name": user.full_name,
            "role": user.role.value,
            "organisation_name": getattr(user.buyer_profile, "organisation_name", None)
            if user.buyer_profile
            else None,
            "buyer_type": getattr(user.buyer_profile, "buyer_type", None).value
            if getattr(user.buyer_profile, "buyer_type", None)
            else None,
            "verification_status": getattr(user.buyer_profile, "verification_status", None).value
            if getattr(user.buyer_profile, "verification_status", None)
            else None,
            "district": user.district,
        }
        demands, _ = demands_service.list_demands(buyer_user_id=user.id, page=1, page_size=5)
        recent_lots = (
            LotService(self.session).list_lots(
                commodity_id=demands[0].commodity_id if demands else None,
                page=1,
                page_size=5,
            )[0]
            if demands
            else []
        )
        offers, _ = offers_service.list_offers(user=user, role_view="outgoing", page=1, page_size=5)
        orders, _ = orders_service.list_orders(user=user, page=1, page_size=5)
        return BuyerDashboard(
            generated_at=datetime.now(UTC),
            greeting=_greeting(user),
            buyer=buyer,
            stats=[
                _stat("Open requirements", open_demands),
                _stat("Quantity wanted", open_value, unit="quintal"),
                _stat("Offers submitted", pending_offers),
                _stat(
                    "Amount payable",
                    float(outstanding.get("pending", 0.0) or 0.0),
                    unit="INR",
                    display=f"₹{float(outstanding.get('pending', 0.0) or 0.0):,.0f}",
                ),
                _stat("Recommended lots", len(matches)),
            ],
            open_demands=[demands_service.enrich(demand) for demand in demands],
            recent_lots=[LotService(self.session).enrich(lot) for lot in recent_lots],
            offers=[offers_service.enrich(offer, viewer=user) for offer in offers],
            orders=[orders_service.enrich(order, viewer=user) for order in orders],
            recommended_lots=[match.model_dump(mode="json") for match in matches],
            notifications=self._notification_cards(user),
            is_demo_data=self._prices_are_synthetic(),
        )

    # -------------------------------------------------------------- admin
    def admin_dashboard(self) -> AdminDashboard:
        by_role = self.users.count_by_role()
        registrations = {
            "by_role": dict(by_role),
            "active_users": self.users.count_active(),
            "new_last_30_days": self.users.count_new_since(30),
            "by_district": [
                {"district": district, "users": count}
                for district, count in self.users.district_breakdown()
            ],
        }
        trade_value = self.orders_repo.trade_value_since(30)
        completed_orders = (
            self.session.query(func.count(Order.id))
            .filter(Order.status == OrderStatus.COMPLETED)
            .scalar()
            or 0
        )
        platform_payment = self.payments.platform_summary()
        demand_by_commodity = self._demand_by_commodity()
        activity = self._district_activity()
        price_movement = self._price_movement()

        pending_orders = (
            self.session.query(func.count(Order.id))
            .filter(Order.status.in_(PENDING_ORDER_STATUSES))
            .scalar()
            or 0
        )
        pending_actions = {
            "open_grievances": self.grievances.counts_by_status().get(
                GrievanceStatus.OPEN.value, 0
            ),
            "unassigned_logistics": self.logistics.unassigned_count(),
            "pending_inspections": len(self.inspections.pending_verification()),
            "pending_buyers": self.session.query(
                func.count(func.distinct(BuyerDemand.buyer_user_id))
            )
            .filter(BuyerDemand.status.in_(OPEN_DEMAND_STATUSES))
            .scalar()
            or 0,
        }
        system_health = {
            "database": "up",
            "commodities": self.session.query(func.count(Commodity.id)).scalar() or 0,
            "districts": len(self.session.query(func.distinct(User.district)).all()),
            "demo_price_data": self._prices_are_synthetic(),
        }
        return AdminDashboard(
            generated_at=datetime.now(UTC),
            stats=[
                _stat("Registered users", sum(by_role.values()), hint="All roles"),
                _stat("New in 30 days", registrations["new_last_30_days"]),
                _stat(
                    "Active lots",
                    self.session.query(func.count(FarmLot.id))
                    .filter(FarmLot.status.in_(ACTIVE_LOT_STATUSES))
                    .scalar()
                    or 0,
                ),
                _stat("Open demands", pending_actions["pending_buyers"]),
                _stat("Completed orders", completed_orders),
                _stat("Trade value (30d)", trade_value, unit="INR", display=f"₹{trade_value:,.0f}"),
                _stat(
                    "Payments pending",
                    float(platform_payment.get("pending", 0.0) or 0.0),
                    unit="INR",
                    display=f"₹{float(platform_payment.get('pending', 0.0) or 0.0):,.0f}",
                ),
                _stat("Open grievances", pending_actions["open_grievances"]),
            ],
            registrations=registrations,
            trade={
                "trade_value_30d": trade_value,
                "trade_value_90d": self.orders_repo.trade_value_since(90),
                "completed_orders": completed_orders,
                "pending_orders": pending_orders,
                "payments": platform_payment,
            },
            demand_by_commodity=demand_by_commodity,
            activity_by_district=activity,
            price_movement=price_movement,
            pending_actions=pending_actions,
            system_health=system_health,
            is_demo_data=self._prices_are_synthetic(),
        )

    # ------------------------------------------------------------ helpers
    def _demand_by_commodity(self, limit: int = 8) -> list[dict[str, Any]]:
        rows = (
            self.session.query(
                Commodity.id,
                Commodity.name,
                func.count(BuyerDemand.id).label("demands"),
                func.coalesce(func.sum(BuyerDemand.required_quantity), 0.0).label("wanted"),
            )
            .join(BuyerDemand, BuyerDemand.commodity_id == Commodity.id)
            .filter(BuyerDemand.status.in_(OPEN_DEMAND_STATUSES))
            .group_by(Commodity.id, Commodity.name)
            .order_by(func.sum(BuyerDemand.required_quantity).desc())
            .limit(limit)
            .all()
        )
        result: list[dict[str, Any]] = []
        for commodity_id, name, demands, wanted in rows:
            listed = (
                self.session.query(func.coalesce(func.sum(FarmLot.available_quantity), 0.0))
                .filter(
                    FarmLot.commodity_id == commodity_id,
                    FarmLot.status.in_(ACTIVE_LOT_STATUSES),
                )
                .scalar()
                or 0.0
            )
            active_lots = (
                self.session.query(func.count(FarmLot.id))
                .filter(
                    FarmLot.commodity_id == commodity_id,
                    FarmLot.status.in_(ACTIVE_LOT_STATUSES),
                )
                .scalar()
                or 0
            )
            modal = self._median_modal_price(commodity_id)
            ratio = float(wanted) / float(listed) if listed else None
            result.append(
                {
                    "commodity_id": str(commodity_id),
                    "commodity_name": name,
                    "open_demands": demands,
                    "demanded_quintal": round(float(wanted), 2),
                    "active_lots": active_lots,
                    "listed_quintal": round(float(listed), 2),
                    "median_modal_price": modal,
                    "demand_supply_ratio": round(ratio, 2) if ratio is not None else None,
                    "demand_level": "HIGH"
                    if ratio and ratio >= 1.8
                    else "MEDIUM"
                    if ratio and ratio >= 0.9
                    else "LOW",
                }
            )
        return result

    def _median_modal_price(self, commodity_id: object) -> float | None:
        values = [
            float(row[0])
            for row in self.session.query(MarketPrice.modal_price)
            .filter(
                MarketPrice.commodity_id == commodity_id,
                MarketPrice.price_date >= (datetime.now(UTC) - timedelta(days=7)).date(),
            )
            .all()
        ]
        if not values:
            return None
        values.sort()
        mid = len(values) // 2
        median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
        return round(median, 2)

    def _district_activity(self, limit: int = 8) -> list[dict[str, Any]]:
        """Users, lots and settled trade value per district."""
        rows = (
            self.session.query(
                User.district,
                func.count(func.distinct(User.id)).label("users"),
                func.count(func.distinct(FarmLot.id)).label("lots"),
            )
            .outerjoin(FarmLot, FarmLot.seller_user_id == User.id)
            .filter(User.district.isnot(None))
            .group_by(User.district)
            .order_by(func.count(func.distinct(User.id)).desc())
            .limit(limit)
            .all()
        )
        since = datetime.now(UTC) - timedelta(days=90)
        activity: list[dict[str, Any]] = []
        for district, users, lots in rows:
            farmer_count = (
                self.session.query(func.count(User.id))
                .join(User.primary_role)
                .filter(User.district == district, User.primary_role.has(name="FARMER"))
                .scalar()
                or 0
            )
            fpo_count = (
                self.session.query(func.count(User.id))
                .join(User.primary_role)
                .filter(User.district == district, User.primary_role.has(name="FPO"))
                .scalar()
                or 0
            )
            trade_value = (
                self.session.query(func.coalesce(func.sum(Transaction.total_amount), 0.0))
                .join(Order, Transaction.order_id == Order.id)
                .filter(
                    Order.pickup_district == district,
                    Transaction.initiated_at >= since,
                )
                .scalar()
                or 0.0
            )
            avg_price = self.session.query(
                func.avg(MarketPrice.modal_price),
            ).scalar()
            top_commodity = (
                self.session.query(Commodity.name)
                .join(Order, Order.commodity_id == Commodity.id)
                .filter(Order.pickup_district == district)
                .group_by(Commodity.name)
                .order_by(func.count(Order.id).desc())
                .limit(1)
                .scalar()
            )
            activity.append(
                {
                    "district": district,
                    "farmers": farmer_count,
                    "fpos": fpo_count,
                    "active_lots": lots,
                    "trade_value": round(float(trade_value), 2),
                    "avg_price": round(float(avg_price), 2) if avg_price else None,
                    "top_commodity": top_commodity,
                    "users": users,
                }
            )
        return activity

    def _price_movement(self, limit: int = 6) -> list[dict[str, Any]]:
        service = MarketService(self.session)
        cards = service.commodity_price_overview(limit=limit)
        movement: list[dict[str, Any]] = []
        for card in cards:
            commodity_id = card.get("commodity_id")
            if commodity_id is None:
                continue
            try:
                change = service.trend(
                    uuid.UUID(str(commodity_id)),
                    days=7,
                ).overall_change_pct
            except Exception:
                change = None
            movement.append(
                {
                    "commodity_id": str(commodity_id),
                    # The overview row names these `commodity` and
                    # `median_modal_price`, not `name` and `modal_price`, which is
                    # the naming the per-commodity price cards use. Reading the
                    # wrong pair silently produced a table of nulls.
                    "commodity_name": card.get("commodity"),
                    "modal_price": card.get("median_modal_price"),
                    "change_pct_7d": change,
                    "direction": "up"
                    if (change or 0) > 0.5
                    else "down"
                    if (change or 0) < -0.5
                    else "flat",
                    # The overview reports no single price date: it spans the
                    # latest row per market. The trend is the dated series.
                    "as_of": None,
                }
            )
        return movement


def role_dashboard(
    session: Session, user: User
) -> FarmerDashboard | BuyerDashboard | AdminDashboard:
    """Dispatch to the dashboard matching the caller's role.

    Raises for roles that have no dashboard. Falling through to the seller view
    would fail response validation with a 422 and no explanation; a 403 naming
    the problem is what a client can actually act on.
    """
    service = DashboardService(session)
    if user.role is UserRole.BUYER:
        return service.buyer_dashboard(user)
    if user.role is UserRole.ADMIN:
        return service.admin_dashboard()
    if user.role in (UserRole.FARMER, UserRole.FPO):
        return service.farmer_dashboard(user)
    raise PermissionDeniedError(
        f"There is no dashboard for the {user.role.value.replace('_', ' ')} role. "
        "Use the role's own endpoints instead.",
        code="NO_DASHBOARD_FOR_ROLE",
    )


__all__ = ["DashboardService", "role_dashboard"]
