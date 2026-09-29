"""Price discovery engine.

A transparent, deterministic model - not a black box. It blends:

* current market modal prices (weighted by proximity to the seller)
* 7/30 day price momentum
* market arrival pressure (heavy arrivals push prices down)
* open buyer demand for the commodity
* distance & transport cost drag
* storage availability (lets the farmer wait for a better window)
* quality grade premium

Every contribution is reported in ``factors`` so the UI can explain the number.
An LLM (see ``app.ai``) may rephrase this output, but never replaces it.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.enums import ConfidenceLevel, LotStatus, QualityGrade
from app.core.logging import get_logger
from app.schemas.ai import AIFactor, MarketSuggestion, PriceDiscoveryResponse, SellingWindow

logger = get_logger(__name__)

DISCLAIMER = (
    "This is a data-assisted estimate built from published mandi rates, recorded "
    "arrivals and demand on KisanSaathi. It is informational only, is not a price "
    "guarantee, and is not an offer to buy or sell."
)

GRADE_PREMIUM: dict[QualityGrade, float] = {
    QualityGrade.GRADE_A: 1.0,
    QualityGrade.GRADE_B: 0.88,
    QualityGrade.GRADE_C: 0.75,
}

# Estimated transport cost in Rs per quintal per km (loaded tempo average).
TRANSPORT_COST_PER_QUINTAL_KM = 3.2
# Perishability: how sharply value decays with each day of delay (fraction/day).
PERISHABILITY_DECAY: dict[QualityGrade, float] = {
    QualityGrade.GRADE_A: 0.035,
    QualityGrade.GRADE_B: 0.05,
    QualityGrade.GRADE_C: 0.07,
}


@dataclass
class DiscoveryInput:
    commodity_id: uuid.UUID
    district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    quality_grade: QualityGrade = QualityGrade.GRADE_A
    quantity_quintal: float = 0.0
    has_storage: bool = False
    storage_cost_per_quintal_day: float = 2.0
    unit: str = "quintal"


@dataclass
class DiscoveryResult:
    response: PriceDiscoveryResponse
    raw: dict[str, Any] = field(default_factory=dict)


def _pct_change(current: float, previous: float) -> float:
    if not previous:
        return 0.0
    return (current - previous) / previous * 100.0


class PriceDiscoveryEngine:
    """Rule based engine with explicit, auditable maths."""

    def __init__(self, market_service: Any, demand_repository: Any, lot_repository: Any) -> None:
        self.market = market_service
        self.demands = demand_repository
        self.lots = lot_repository

    # ------------------------------------------------------------------ run
    def discover(self, payload: DiscoveryInput) -> DiscoveryResult:
        market = self.market
        commodity = market.get_commodity(payload.commodity_id)

        snapshot = market.price_snapshot(
            commodity.id,
            district=payload.district,
            origin_latitude=payload.latitude,
            origin_longitude=payload.longitude,
        )
        markets: list[dict[str, Any]] = snapshot["markets"]
        if not markets:
            return DiscoveryResult(
                response=PriceDiscoveryResponse(
                    commodity_id=commodity.id,
                    commodity_name=commodity.name,
                    unit=commodity.default_unit,
                    current_market_range=(0.0, 0.0),
                    estimated_fair_price_range=(0.0, 0.0),
                    trend_direction="STABLE",
                    demand_level="UNKNOWN",
                    confidence=ConfidenceLevel.LOW,
                    confidence_score=20.0,
                    factors=[
                        AIFactor(
                            code="no_data",
                            label="No market data",
                            impact="NEGATIVE",
                            detail=(
                                "No mandi prices have been recorded for this commodity yet. "
                                "Connect a market data provider to improve this estimate."
                            ),
                        )
                    ],
                    generated_at=datetime.now(UTC),
                    disclaimer=DISCLAIMER,
                )
            )

        modal = [m["modal_price"] for m in markets]
        base_low = min(modal)
        base_high = max(modal)
        if payload.district:
            district_modals = [
                m["modal_price"] for m in markets if m["district"] == payload.district
            ]
            district_median = (
                sum(district_modals) / len(district_modals) if district_modals else None
            )
        else:
            district_median = sum(modal) / len(modal)
        if district_median is None:
            district_median = sum(modal) / len(modal)

        factors: list[AIFactor] = []

        # --- momentum -------------------------------------------------
        trend_7 = market.trend(commodity.id, days=7, district=payload.district)
        trend_30 = market.trend(commodity.id, days=30, district=payload.district)
        change_7 = trend_7.overall_change_pct
        change_30 = trend_30.overall_change_pct
        momentum_pct = (change_7 or 0.0) * 0.65 + (change_30 or 0.0) * 0.35
        momentum_pct = max(-15.0, min(15.0, momentum_pct))
        if change_7 is not None:
            factors.append(
                AIFactor(
                    code="recent_price_movement",
                    label="Recent price movement",
                    impact="POSITIVE"
                    if change_7 > 0.5
                    else ("NEGATIVE" if change_7 < -0.5 else "NEUTRAL"),
                    detail=(
                        f"Modal price moved {change_7:+.1f}% over the last 7 days "
                        f"({change_30:+.1f}% over 30 days)."
                        if change_30 is not None
                        else f"Modal price moved {change_7:+.1f}% over the last 7 days."
                    ),
                    weight=abs(momentum_pct),
                )
            )

        # --- arrivals -------------------------------------------------
        arrivals = market.arrivals_for_commodity(commodity.id, days=3, district=payload.district)
        recent, previous = arrivals["recent"], arrivals["previous"]
        arrival_change = _pct_change(recent, previous)
        arrival_factor_pct = 0.0
        if previous > 0:
            arrival_factor_pct = -max(-6.0, min(6.0, arrival_change * 0.35))
        if arrival_change:
            factors.append(
                AIFactor(
                    code="market_arrivals",
                    label="Market arrivals",
                    impact="POSITIVE"
                    if arrival_factor_pct > 0.4
                    else ("NEGATIVE" if arrival_factor_pct < -0.4 else "NEUTRAL"),
                    detail=(
                        f"{recent:,.0f} quintal arrived in the last 3 days "
                        f"({arrival_change:+.0f}% vs the previous 3 days). "
                        + (
                            "Lighter arrivals usually support prices."
                            if arrival_change < 0
                            else "Heavier arrivals usually soften prices."
                        )
                    ),
                    weight=abs(arrival_factor_pct),
                )
            )

        # --- buyer demand ---------------------------------------------
        open_demands = self.demands.open_demands_for_commodity(commodity.id)
        demanded_quintal = sum(
            max(0.0, d.required_quantity - d.fulfilled_quantity) for d in open_demands
        )
        supplied_quintal = self._listed_quantity(commodity.id, payload.district)
        demand_level, demand_pct, demand_signal = self._demand_level(
            demanded_quintal, supplied_quintal, len(open_demands)
        )
        factors.append(
            AIFactor(
                code="buyer_demand",
                label="Buyer demand on platform",
                impact="POSITIVE"
                if demand_pct > 0.3
                else ("NEGATIVE" if demand_pct < -0.3 else "NEUTRAL"),
                detail=(
                    f"{len(open_demands)} open buyer requirement(s) for {commodity.name} "
                    f"totalling {demanded_quintal:,.0f} quintal against {supplied_quintal:,.0f} "
                    f"quintal listed. Demand assessed as {demand_level}."
                ),
                weight=abs(demand_pct),
            )
        )

        # --- suggested markets and transport drag ----------------------
        suggestions = self._rank_markets(
            markets,
            quality_grade=payload.quality_grade,
            momentum_pct=momentum_pct,
            arrival_factor_pct=arrival_factor_pct,
            demand_pct=demand_pct,
        )
        if suggestions and payload.quantity_quintal > 0:
            best = suggestions[0]
            if best.net_price_after_transport is not None:
                factors.append(
                    AIFactor(
                        code="distance",
                        label="Distance & transport cost",
                        impact="NEGATIVE"
                        if best.net_price_after_transport < best.modal_price
                        else "NEUTRAL",
                        detail=(
                            f"{best.market_name} pays ₹{best.modal_price:,.0f} but about "
                            f"₹{best.modal_price - (best.net_price_after_transport or 0):,.0f} "
                            "per quintal is absorbed by transport for this quantity."
                        ),
                        weight=0.0,
                    )
                )

        transport_estimate = None
        if suggestions and suggestions[0].net_price_after_transport is not None:
            transport_estimate = round(
                suggestions[0].modal_price - suggestions[0].net_price_after_transport, 2
            )

        # --- fair price range -----------------------------------------
        fair_mid = district_median * (1 + momentum_pct / 100) * (1 + arrival_factor_pct / 100)
        fair_mid *= 1 + demand_pct / 100
        fair_mid *= GRADE_PREMIUM[payload.quality_grade]
        spread = max(0.05, 0.11 - abs(momentum_pct) / 400)
        fair_low = max(1.0, fair_mid * (1 - spread))
        fair_high = fair_mid * (1 + spread)

        # --- selling window -------------------------------------------
        window, decay_pct = self._selling_window(
            momentum_pct=momentum_pct,
            demand_pct=demand_pct,
            arrival_factor_pct=arrival_factor_pct,
            quality_grade=payload.quality_grade,
            has_storage=payload.has_storage,
            storage_cost_per_quintal_day=payload.storage_cost_per_quintal_day,
            quantity_quintal=payload.quantity_quintal,
            base_price=fair_mid,
        )
        if decay_pct:
            factors.append(
                AIFactor(
                    code="holding_cost",
                    label="Storage & perishability cost",
                    impact="NEGATIVE",
                    detail=(
                        f"Delaying beyond the suggested window costs about "
                        f"{decay_pct:.1f}% of value per day"
                        + (
                            " (rented godown rates applied)."
                            if payload.has_storage
                            else " (no storage declared, spoilage risk applied)."
                        )
                    ),
                    weight=abs(decay_pct),
                )
            )
        if payload.has_storage:
            factors.append(
                AIFactor(
                    code="storage_available",
                    label="Storage available",
                    impact="POSITIVE",
                    detail=(
                        "You declared storage, so you can hold the produce and wait for a "
                        "better window instead of selling immediately after harvest."
                    ),
                )
            )

        # --- confidence ------------------------------------------------
        score, confidence = self._confidence(
            market_count=len(markets),
            trend_points=len(trend_7.points),
            has_arrivals=recent > 0,
            demand_records=len(open_demands),
            change_7=change_7,
        )
        factors.append(
            AIFactor(
                code="data_coverage",
                label="Data coverage",
                impact="POSITIVE" if score >= 65 else "NEUTRAL",
                detail=(
                    f"Based on {len(markets)} market price records, {len(trend_7.points)} days "
                    f"of history and {len(open_demands)} open buyer requirement(s)."
                ),
                weight=score / 100,
            )
        )

        price_position = None
        if fair_low < district_median < fair_high or base_low <= district_median <= base_high:
            position_low, position_high = base_low, base_high
            if position_high > position_low:
                price_position = round(
                    (district_median - position_low) / (position_high - position_low) * 100, 1
                )

        trend_direction = "STABLE"
        if change_7 is not None:
            if change_7 > 1.5:
                trend_direction = "RISING"
            elif change_7 < -1.5:
                trend_direction = "FALLING"

        storage_advice = None
        if payload.has_storage:
            hold_days = (window.end - window.start).days if window.end and window.start else 0
            storage_cost = (
                payload.quantity_quintal * payload.storage_cost_per_quintal_day * max(hold_days, 0)
            )
            storage_advice = (
                f"Holding {payload.quantity_quintal:,.0f} quintal for {max(hold_days, 0)} day(s) "
                f"costs about ₹{storage_cost:,.0f} in storage. This is included in the window "
                "estimate above."
            )

        response = PriceDiscoveryResponse(
            commodity_id=commodity.id,
            commodity_name=commodity.name,
            unit=commodity.default_unit,
            current_market_range=(round(base_low, 2), round(base_high, 2)),
            estimated_fair_price_range=(round(fair_low, 2), round(fair_high, 2)),
            district_modal_price=round(district_median, 2),
            price_position_pct=price_position,
            trend_direction=trend_direction,
            trend_change_pct=change_7,
            demand_level=demand_level,
            demand_signal=demand_signal,
            suggested_markets=suggestions,
            selling_window=window,
            confidence=confidence,
            confidence_score=score,
            factors=factors,
            storage_advice=storage_advice,
            transport_estimate=transport_estimate,
            is_demo_data=snapshot["is_demo_data"],
            generated_at=datetime.now(UTC),
            disclaimer=DISCLAIMER,
        )
        return DiscoveryResult(
            response=response,
            raw={
                "momentum_pct": momentum_pct,
                "arrival_change_pct": arrival_change,
                "demanded_quintal": demanded_quintal,
                "supplied_quintal": supplied_quintal,
                "base_low": base_low,
                "base_high": base_high,
            },
        )

    # ------------------------------------------------------------- helpers
    def _listed_quantity(self, commodity_id: uuid.UUID, district: str | None) -> float:
        stmt = self.lots.browse_query(
            status=[LotStatus.PUBLISHED, LotStatus.UNDER_OFFER],
            commodity_id=commodity_id,
            district=district,
        )
        lots = self.lots.session.execute(stmt).unique().scalars().all()
        return sum(lot.available_quantity for lot in lots)

    @staticmethod
    def _demand_level(
        demanded: float, supplied: float, demand_records: int
    ) -> tuple[str, float, str]:
        if demanded <= 0:
            return "LOW", 0.0, "No open buyer requirements recorded."
        ratio = demanded / supplied if supplied > 0 else 2.0
        if ratio >= 1.8:
            level = "HIGH"
        elif ratio >= 0.9:
            level = "MEDIUM"
        else:
            level = "LOW"
        pct = max(-8.0, min(12.0, (ratio - 1.0) * 9.0))
        signal = (
            f"{demand_records} open requirement(s) totalling {demanded:,.0f} quintal vs "
            f"{supplied:,.0f} quintal listed (ratio {ratio:.2f})."
        )
        return level, pct, signal

    @staticmethod
    def _rank_markets(
        markets: list[dict[str, Any]],
        *,
        quality_grade: QualityGrade,
        momentum_pct: float,
        arrival_factor_pct: float,
        demand_pct: float,
    ) -> list[MarketSuggestion]:
        premium = GRADE_PREMIUM[quality_grade]
        scored: list[tuple[float, dict[str, Any], float | None]] = []
        for market in markets:
            distance = market.get("distance_km")
            transport = (
                round(distance * TRANSPORT_COST_PER_QUINTAL_KM, 2) if distance is not None else None
            )
            net = (
                round(market["modal_price"] - transport, 2)
                if transport is not None
                else market["modal_price"]
            )
            # Net realisation is what the farmer actually gets; weight it heavily.
            score = (
                net
                * premium
                * (1 + momentum_pct / 300)
                * (1 + arrival_factor_pct / 200)
                * (1 + demand_pct / 400)
            )
            if distance is not None and distance > 250:
                score *= 0.9
            scored.append((score, market, net))

        scored.sort(key=lambda item: item[0], reverse=True)
        suggestions: list[MarketSuggestion] = []
        for index, (_score, market, net) in enumerate(scored[:5], start=1):
            distance = market.get("distance_km")
            if distance is None:
                reason = (
                    "Highest modal price in the latest feed "
                    f"(₹{market['modal_price']:,.0f}/quintal)."
                )
            else:
                reason = (
                    f"₹{market['modal_price']:,.0f}/quintal modal price"
                    + (f", about {distance:,.0f} km away" if distance else " in your district")
                    + f"; estimated net after transport ₹{net:,.0f}."
                )
            suggestions.append(
                MarketSuggestion(
                    market_id=uuid.UUID(str(market["market_id"])),
                    market_name=str(market["market_name"]),
                    district=str(market["district"]),
                    modal_price=float(market["modal_price"]),
                    distance_km=distance,
                    net_price_after_transport=net,
                    rank=index,
                    reason=reason,
                )
            )
        return suggestions

    @staticmethod
    def _selling_window(
        *,
        momentum_pct: float,
        demand_pct: float,
        arrival_factor_pct: float,
        quality_grade: QualityGrade,
        has_storage: bool,
        storage_cost_per_quintal_day: float,
        quantity_quintal: float,
        base_price: float,
    ) -> tuple[SellingWindow, float]:
        """Choose a 2-5 day window from a simple weighted score per horizon."""
        today = date.today()
        decay = PERISHABILITY_DECAY[quality_grade]
        if not has_storage:
            decay *= 1.6
        best_horizon, best_score = 0, -1e9
        scores: dict[int, float] = {}
        for horizon in range(0, 6):
            # expected drift from momentum, damped by arrivals, boosted by demand
            drift = horizon * (
                momentum_pct / 100 * 0.55 + demand_pct / 100 * 0.35 + arrival_factor_pct / 100 * 0.2
            )
            cost_pct = decay * horizon
            if has_storage:
                storage_pct = (
                    storage_cost_per_quintal_day * horizon / base_price * 100 if base_price else 0.0
                )
            else:
                storage_pct = 0.0
            score = drift - cost_pct - storage_pct
            scores[horizon] = score
            if score > best_score:
                best_score, best_horizon = score, horizon

        start = today + timedelta(days=best_horizon)
        end = start + timedelta(days=2)
        if best_horizon == 0:
            label = "Sell now"
            rationale = (
                "Current market rates are at or near their recent best, and waiting is "
                "expected to cost more in storage and spoilage than the price gain."
            )
        else:
            label = f"Next {best_horizon}-{best_horizon + 2} days"
            rationale = (
                f"Projected movement over {best_horizon} day(s) is stronger than the "
                f"{decay * 100:.1f}% per day holding cost"
                + (" (you have storage available)." if has_storage else " (no storage declared).")
            )
        if quantity_quintal and has_storage:
            rationale += (
                f" Storage cost for {quantity_quintal:,.0f} quintal over this period is about "
                f"₹{quantity_quintal * storage_cost_per_quintal_day * best_horizon:,.0f}."
            )
        return (
            SellingWindow(start=start, end=end, label=label, rationale=rationale),
            decay * 100,
        )

    @staticmethod
    def _confidence(
        *,
        market_count: int,
        trend_points: int,
        has_arrivals: bool,
        demand_records: int,
        change_7: float | None,
    ) -> tuple[float, ConfidenceLevel]:
        score = 20.0
        score += min(25.0, market_count * 3.5)
        score += min(20.0, trend_points * 2.0)
        score += 12.0 if has_arrivals else 0.0
        score += min(15.0, demand_records * 5.0)
        if change_7 is not None and abs(change_7) > 25:
            score -= 10.0  # very volatile markets are harder to forecast
        score = max(10.0, min(95.0, score))
        if score >= 70:
            return round(score, 1), ConfidenceLevel.HIGH
        if score >= 45:
            return round(score, 1), ConfidenceLevel.MEDIUM
        return round(score, 1), ConfidenceLevel.LOW


def discount_for_volume(quantity_quintal: float) -> float:
    """Small bulk incentive used in explanations (0.5% - 3%)."""
    if quantity_quintal >= 500:
        return 3.0
    if quantity_quintal >= 200:
        return 2.0
    if quantity_quintal >= 50:
        return 1.0
    return 0.5


def annualise(change_pct: float) -> float:  # pragma: no cover - reserved for analytics
    return (1 + change_pct / 100) ** 12 - 1


def safe_exp(value: float) -> float:  # pragma: no cover - numerical guard
    try:
        return math.exp(max(-20.0, min(20.0, value)))
    except OverflowError:
        return 0.0
