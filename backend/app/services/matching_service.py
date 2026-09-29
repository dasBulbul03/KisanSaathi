"""Matching engine: score farmer lots against buyer demands and vice versa.

The score is a weighted sum of independent, individually reported criteria. Every
criterion is surfaced as a reason (satisfied or not) so a 92% match can be
explained, and a non-satisfied criterion always lowers the score and is shown.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import (
    DemandStatus,
    LotStatus,
    QualityGrade,
    UserRole,
    VerificationStatus,
)
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models import BuyerDemand, FarmLot, Order
from app.repositories.trade import (
    DemandRepository,
    LotRepository,
    OrderRepository,
    demands_for_matching,
    lots_for_matching,
)
from app.schemas.trade import MATCH_DISCLAIMER, MatchReason, MatchResult
from app.utils.geo import distance_between
from app.utils.units import convert_quantity, normalise_unit

logger = get_logger(__name__)

GRADE_RANK: dict[QualityGrade, int] = {
    QualityGrade.GRADE_A: 3,
    QualityGrade.GRADE_B: 2,
    QualityGrade.GRADE_C: 1,
}

#: Roles that publish lots, and therefore get demand recommendations.
_SELLER_ROLE_VALUES = frozenset(
    {UserRole.FARMER.value, UserRole.FPO.value, "SELLER", "FARMER", "FPO"}
)
#: Roles that raise demands, and therefore get lot recommendations.
_BUYER_ROLE_VALUES = frozenset({UserRole.BUYER.value, "BUYER"})

CRITERIA_WEIGHTS: dict[str, float] = {
    "commodity": 22.0,
    "quantity": 18.0,
    "quality": 16.0,
    "distance": 14.0,
    "timing": 12.0,
    "price": 10.0,
    "trust": 8.0,
}


def _score_label(score: float) -> str:
    if score >= 85:
        return "Excellent match"
    if score >= 70:
        return "Strong match"
    if score >= 55:
        return "Possible match"
    if score >= 40:
        return "Weak match"
    return "Low match"


def _grade_meets(supplied: QualityGrade, required: QualityGrade) -> bool:
    return GRADE_RANK[supplied] >= GRADE_RANK[required]


class MatchingService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.lots = LotRepository(FarmLot, session)
        self.demands = DemandRepository(BuyerDemand, session)
        self.orders = OrderRepository(Order, session)

    # -------------------------------------------------------- lot -> buyer
    def match_lot_to_demands(
        self, lot: FarmLot, *, commodity: Any, limit: int = 20
    ) -> list[MatchResult]:
        candidates = demands_for_matching(self.demands, commodity_id=lot.commodity_id)
        results: list[MatchResult] = []
        for demand in candidates:
            if demand.buyer_user_id == lot.seller_user_id:
                continue
            result = self._score_lot_demand(lot, demand, commodity)
            if result is not None:
                results.append(result)
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _score_lot_demand(
        self, lot: FarmLot, demand: BuyerDemand, commodity: Any
    ) -> MatchResult | None:
        reasons: list[MatchReason] = []
        warnings: list[str] = []
        score = 0.0

        # 1. commodity -----------------------------------------------------
        commodity_ok = lot.commodity_id == demand.commodity_id
        reasons.append(
            MatchReason(
                code="commodity",
                label="Commodity matches",
                satisfied=commodity_ok,
                weight=CRITERIA_WEIGHTS["commodity"],
                detail=commodity.name if commodity_ok else "Commodity differs",
            )
        )
        if commodity_ok:
            score += CRITERIA_WEIGHTS["commodity"]

        # 2. quantity ------------------------------------------------------
        remaining = max(0.0, demand.required_quantity - demand.fulfilled_quantity)
        lot_qty = convert_quantity(lot.available_quantity, lot.unit, demand.unit)
        quantity_ratio = lot_qty / remaining if remaining > 0 else 1.0
        quantity_ok = quantity_ratio >= 0.5
        if quantity_ratio >= 1.0:
            quantity_score = CRITERIA_WEIGHTS["quantity"]
        else:
            quantity_score = CRITERIA_WEIGHTS["quantity"] * max(0.0, quantity_ratio)
        score += quantity_score
        reasons.append(
            MatchReason(
                code="quantity",
                label="Required quantity available",
                satisfied=quantity_ok,
                weight=CRITERIA_WEIGHTS["quantity"],
                detail=(
                    f"{lot.available_quantity:,.0f} {lot.unit} available against "
                    f"{remaining:,.0f} {demand.unit} still required"
                ),
            )
        )
        if quantity_ratio < 1.0:
            warnings.append(
                f"Only {lot_qty:,.0f} {demand.unit} of the {remaining:,.0f} {demand.unit} "
                "requirement can be served from this lot."
            )

        # 3. quality grade -------------------------------------------------
        grade_ok = _grade_meets(lot.quality_grade, demand.min_grade)
        reasons.append(
            MatchReason(
                code="quality",
                label="Quality requirement satisfied",
                satisfied=grade_ok,
                weight=CRITERIA_WEIGHTS["quality"],
                detail=(
                    f"Lot is {lot.quality_grade.label}, requirement is "
                    f"{demand.min_grade.label} or better"
                ),
            )
        )
        if grade_ok:
            score += CRITERIA_WEIGHTS["quality"]
        else:
            score += CRITERIA_WEIGHTS["quality"] * 0.3

        # 4. distance ------------------------------------------------------
        distance = distance_between(
            lot.latitude,
            lot.longitude,
            demand.latitude,
            demand.longitude,
            lot.district,
            demand.district,
        )
        radius = demand.max_pickup_radius_km
        distance_ok = distance.km is not None and distance.km <= radius
        if distance.km is None:
            distance_score = CRITERIA_WEIGHTS["distance"] * 0.6
            distance_detail = (
                f"Pickup location {lot.district or 'not specified'} → delivery "
                f"{demand.district or demand.delivery_location}; exact distance unknown"
            )
        else:
            ratio = distance.km / radius if radius else 1.0
            distance_score = CRITERIA_WEIGHTS["distance"] * max(0.0, 1.0 - ratio * 0.85)
            distance_detail = (
                f"{distance.km:,.0f} km from pickup to delivery (limit {radius:,.0f} km)"
            )
            if not distance_ok:
                warnings.append(
                    f"Pickup is {distance.km:,.0f} km away, beyond the buyer's preferred "
                    f"{radius:,.0f} km pickup radius."
                )
        score += distance_score
        reasons.append(
            MatchReason(
                code="distance",
                label="Delivery location within range",
                satisfied=distance_ok,
                weight=CRITERIA_WEIGHTS["distance"],
                detail=distance_detail,
            )
        )

        # 5. timing -------------------------------------------------------
        available = lot.available_from or lot.harvest_date or date.today()
        timing_ok = available <= demand.required_by_date
        slack = (demand.required_by_date - available).days
        timing_score = CRITERIA_WEIGHTS["timing"] * (1.0 if timing_ok else 0.2)
        score += timing_score
        reasons.append(
            MatchReason(
                code="timing",
                label="Delivery date compatible",
                satisfied=timing_ok,
                weight=CRITERIA_WEIGHTS["timing"],
                detail=(
                    f"Produce available from {available.isoformat()}, required by "
                    f"{demand.required_by_date.isoformat()} ({slack} day slack)"
                    if timing_ok
                    else (
                        "Produce is only available from "
                        f"{available.isoformat()}, after the required date"
                    )
                ),
            )
        )
        if not timing_ok:
            warnings.append("Lot becomes available after the buyer's required date.")

        # 6. price --------------------------------------------------------
        ask = lot.expected_price
        ceiling = demand.max_price_per_unit
        floor = demand.min_price_per_unit
        if ask is not None and ceiling is not None and floor is not None:
            if floor <= ask <= ceiling:
                price_ok, price_score, price_detail = (
                    True,
                    CRITERIA_WEIGHTS["price"],
                    (
                        f"Ask ₹{ask:,.0f}/{normalise_unit(demand.unit)} is inside the buyer's "
                        f"₹{floor:,.0f}–₹{ceiling:,.0f} range"
                    ),
                )
            elif ask < floor:
                price_ok, price_score, price_detail = (
                    False,
                    CRITERIA_WEIGHTS["price"] * 0.5,
                    (f"Ask ₹{ask:,.0f} is below the buyer's minimum ₹{floor:,.0f}"),
                )
                warnings.append("Your ask is below the buyer's stated minimum price.")
            else:
                price_ok, price_score = False, CRITERIA_WEIGHTS["price"] * 0.35
                over = (ask - ceiling) / ceiling * 100 if ceiling else 0.0
                price_detail = (
                    f"Ask ₹{ask:,.0f} is {over:.0f}% above the buyer's ceiling ₹{ceiling:,.0f}"
                )
                warnings.append("Your ask is above the buyer's stated maximum price.")
        elif ask is not None:
            price_ok, price_score, price_detail = (
                True,
                CRITERIA_WEIGHTS["price"] * 0.7,
                (
                    f"Ask ₹{ask:,.0f}/{normalise_unit(lot.unit)}; "
                    "buyer has not published a price range"
                ),
            )
        else:
            price_ok, price_score, price_detail = (
                True,
                CRITERIA_WEIGHTS["price"] * 0.5,
                ("No expected price set on the lot"),
            )
        score += price_score
        reasons.append(
            MatchReason(
                code="price",
                label="Price within range",
                satisfied=price_ok,
                weight=CRITERIA_WEIGHTS["price"],
                detail=price_detail,
            )
        )

        # 7. trust --------------------------------------------------------
        buyer_profile = demand.buyer
        verified = bool(
            buyer_profile and buyer_profile.verification_status is VerificationStatus.VERIFIED
        )
        completed = self._completed_orders(demand.buyer_user_id)
        trust_score = CRITERIA_WEIGHTS["trust"] * (
            0.4 + (0.35 if verified else 0.0) + min(0.25, completed * 0.05)
        )
        score += trust_score
        reasons.append(
            MatchReason(
                code="trust",
                label="Buyer reliability signals",
                satisfied=verified,
                weight=CRITERIA_WEIGHTS["trust"],
                detail=(
                    f"Verified buyer with {completed} completed order(s)"
                    if verified
                    else f"Buyer is not verified yet; {completed} completed order(s) on record"
                ),
            )
        )
        if demand.requires_verified_buyer and not verified:
            warnings.append("This requirement is restricted to verified buyers.")
            score -= 4.0

        score = max(0.0, min(100.0, score))
        return MatchResult(
            entity_type="BUYER_DEMAND",
            entity_id=demand.id,
            reference_code=demand.reference_code,
            title=(
                f"Needs {demand.required_quantity:,.0f} {normalise_unit(demand.unit)} of "
                f"{commodity.name} ({demand.min_grade.label}+) at {demand.delivery_location}"
            ),
            score=round(score, 1),
            score_label=_score_label(score),
            commodity=commodity.name,
            quantity=demand.required_quantity,
            unit=normalise_unit(demand.unit),
            grade=demand.min_grade,
            # A range needs both bounds. A demand that names only a ceiling (or
            # only a floor) has no range to report, and passing a one-sided tuple
            # would fail validation for the whole match list.
            price_range=(
                (demand.min_price_per_unit, demand.max_price_per_unit)
                if demand.min_price_per_unit is not None and demand.max_price_per_unit is not None
                else None
            ),
            district=demand.district,
            location=demand.delivery_location,
            distance_km=distance.km,
            is_verified_buyer=verified,
            seller_name=((demand.buyer.organisation_name if demand.buyer else None) or "Buyer"),
            completed_orders=completed,
            rating=None,
            required_by_date=demand.required_by_date,
            available_from=available,
            reasons=reasons,
            warnings=warnings,
            disclaimer=MATCH_DISCLAIMER,
        )

    # -------------------------------------------------------- demand -> lot
    def match_demand_to_lots(
        self, demand: BuyerDemand, *, commodity: Any, limit: int = 20
    ) -> list[MatchResult]:
        candidates = lots_for_matching(
            self.lots, commodity_id=demand.commodity_id, exclude_seller_id=demand.buyer_user_id
        )
        results: list[MatchResult] = []
        for lot in candidates:
            result = self._score_lot_demand(lot, demand, commodity)
            if result is not None:
                results.append(self._to_buyer_view(result, lot, commodity))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _to_buyer_view(self, result: MatchResult, lot: FarmLot, commodity: Any) -> MatchResult:
        seller = lot.seller
        fpo = getattr(seller, "fpo_profile", None) if seller else None
        completed = self._completed_orders(lot.seller_user_id, as_seller=True)
        return MatchResult(
            entity_type="FARM_LOT",
            entity_id=lot.id,
            reference_code=lot.lot_code,
            title=f"{lot.title} - {lot.available_quantity:,.0f} {normalise_unit(lot.unit)}",
            score=result.score,
            score_label=result.score_label,
            commodity=commodity.name,
            quantity=lot.available_quantity,
            unit=normalise_unit(lot.unit),
            grade=lot.quality_grade,
            expected_price=lot.expected_price,
            price_range=None,
            district=lot.district,
            location=", ".join(p for p in [lot.village, lot.taluka, lot.district] if p) or None,
            distance_km=result.distance_km,
            is_verified_buyer=False,
            seller_name=seller.full_name if seller else None,
            seller_organisation=fpo.organisation_name if fpo else None,
            completed_orders=completed,
            rating=None,
            required_by_date=None,
            available_from=lot.available_from or lot.harvest_date,
            reasons=result.reasons,
            warnings=result.warnings,
            disclaimer=MATCH_DISCLAIMER,
        )

    # ------------------------------------------------------------- helpers
    def _completed_orders(self, user_id: uuid.UUID, *, as_seller: bool = False) -> int:
        from app.core.enums import OrderStatus

        terminal = [
            OrderStatus.PAYMENT_COMPLETED,
            OrderStatus.COMPLETED,
            OrderStatus.QUALITY_CONFIRMED,
        ]
        if as_seller:
            return int(self.orders.count(seller_user_id=user_id, status=terminal))
        return int(self.orders.count(buyer_user_id=user_id, status=terminal))

    def matches_for_user(
        self,
        user_id: uuid.UUID,
        *,
        role: str,
        commodity_id: uuid.UUID | None = None,
        limit: int = 20,
    ) -> list[MatchResult]:
        """Matches for one user, on whichever side of the market they trade.

        ``role`` is a :class:`~app.core.enums.UserRole` value. The lowercase
        aliases are accepted too because they read better at the call site; they
        are normalised here rather than trusted, since an unnormalised
        "seller" would silently fall through to the buyer branch and return the
        wrong side's matches.
        """
        normalised = role.value if isinstance(role, UserRole) else str(role).upper()
        if normalised in _SELLER_ROLE_VALUES:
            return self._matches_for_seller(user_id, commodity_id=commodity_id, limit=limit)
        if normalised in _BUYER_ROLE_VALUES:
            return self._matches_for_buyer(user_id, commodity_id=commodity_id, limit=limit)
        raise ValidationError(
            f"Role {normalised!r} has no match side. Use a seller role (FARMER, FPO) " "or BUYER.",
            code="MATCH_ROLE_UNSUPPORTED",
        )

    def _matches_for_seller(
        self, user_id: uuid.UUID, *, commodity_id: uuid.UUID | None, limit: int
    ) -> list[MatchResult]:
        lots = self.lots.find_all(
            filters={
                "seller_user_id": user_id,
                "status": [LotStatus.PUBLISHED, LotStatus.UNDER_OFFER],
            },
            order_by=["-updated_at"],
            limit=20,
        )
        results: list[MatchResult] = []
        seen: set[uuid.UUID] = set()
        for lot in lots:
            if commodity_id and lot.commodity_id != commodity_id:
                continue
            commodity = lot.commodity
            for match in self.match_lot_to_demands(lot, commodity=commodity, limit=10):
                if match.entity_id in seen:
                    continue
                seen.add(match.entity_id)
                results.append(match)
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _matches_for_buyer(
        self, user_id: uuid.UUID, *, commodity_id: uuid.UUID | None, limit: int
    ) -> list[MatchResult]:
        stmt = self.demands.search_query(
            status=[DemandStatus.OPEN, DemandStatus.PARTIALLY_FULFILLED],
            buyer_user_id=user_id,
        )
        if commodity_id:
            stmt = stmt.where(BuyerDemand.commodity_id == commodity_id)
        demands = list(self.session.execute(stmt).unique().scalars().all())
        results: list[MatchResult] = []
        seen: set[uuid.UUID] = set()
        for demand in demands:
            commodity = demand.commodity
            for match in self.match_demand_to_lots(demand, commodity=commodity, limit=10):
                if match.entity_id in seen:
                    continue
                seen.add(match.entity_id)
                results.append(match)
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def summary(self, matches: list[MatchResult]) -> dict[str, Any]:
        return {
            "total_candidates": len(matches),
            "strong_matches": sum(1 for m in matches if m.score >= 70),
        }
