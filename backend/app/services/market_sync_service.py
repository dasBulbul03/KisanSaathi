"""Market data synchronisation.

Pulls price and arrival records from the configured ``MarketDataProvider`` and
upserts them into ``market_prices`` / ``market_arrivals``. The operation is
idempotent: rows are keyed on (market, commodity, date), so re-running a sync
updates in place rather than duplicating.

Every run writes a ``MarketDataSyncLog`` row - including failures - so
administrators can see when a feed broke without digging through logs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import SyncStatus
from app.core.logging import get_logger
from app.integrations.market_data.provider import (
    ArrivalRecord,
    MarketDataProvider,
    PriceRecord,
    get_market_data_provider,
)
from app.models import Commodity, Market, MarketArrival, MarketPrice
from app.repositories.markets import (
    CommodityRepository,
    MarketArrivalRepository,
    MarketPriceRepository,
    MarketRepository,
)
from app.services.market_service import MarketService

logger = get_logger(__name__)

DEFAULT_HISTORY_DAYS = 30
# Only these sources may be written by an automated sync; a live feed should not
# silently overwrite a government-sourced row.
SYNCABLE_SOURCES = {"DEMO", "AGMARKET_API", "STATE_APMC", "PARTNER_API"}


class MarketDataSyncService:
    def __init__(
        self,
        session: Session,
        *,
        provider: MarketDataProvider | None = None,
    ) -> None:
        self.session = session
        self.provider = provider or get_market_data_provider()
        self.commodities = CommodityRepository(Commodity, session)
        self.markets = MarketRepository(Market, session)
        self.prices = MarketPriceRepository(MarketPrice, session)
        self.arrivals = MarketArrivalRepository(MarketArrival, session)
        self.market_service = MarketService(session)

    # ----------------------------------------------------------------- run
    def sync(
        self,
        *,
        days: int = 3,
        history_days: int | None = None,
        commodity_ids: list[uuid.UUID] | None = None,
        market_ids: list[uuid.UUID] | None = None,
        triggered_by_user_id: uuid.UUID | None = None,
        include_arrivals: bool = True,
    ) -> dict[str, Any]:
        started_at = datetime.now(UTC)
        today = started_at.date()
        from_date = today - timedelta(days=max(0, days) - 1)
        processed = inserted = updated = 0
        arrivals_written = 0
        message: str

        try:
            commodities = self._resolve_commodities(commodity_ids)
            markets = self._resolve_markets(market_ids)
            if not commodities or not markets:
                message = "No commodities or markets are configured; nothing to sync."
                records = []
            else:
                records = self._fetch_prices(commodities, markets, from_date, today, history_days)
                for record, market in records:
                    outcome = self._upsert_price(record, commodities, markets, market)
                    processed += 1
                    inserted += outcome == "inserted"
                    updated += outcome == "updated"
                if include_arrivals:
                    arrivals_written = self._sync_arrivals(commodities, markets, from_date, today)
            status = SyncStatus.SUCCESS
            message = f"Synced {inserted} new and {updated} updated price rows."
        except Exception as exc:
            self.session.rollback()
            status = SyncStatus.FAILED
            message = str(exc)
            logger.error("market_data.sync.failed", error=str(exc))

        log = self.market_service.create_sync_log(
            provider=self.provider.name,
            started_at=started_at,
            status=status,
            records_processed=processed,
            records_inserted=inserted,
            records_updated=updated,
            message=message,
        )
        log.finished_at = datetime.now(UTC)
        log.from_date = from_date
        log.to_date = today
        log.triggered_by_user_id = triggered_by_user_id
        self.session.commit()

        return {
            "provider": self.provider.name,
            "status": status.value,
            "records_processed": processed,
            "records_inserted": inserted,
            "records_updated": updated,
            "arrivals_written": arrivals_written,
            "from_date": from_date.isoformat(),
            "to_date": today.isoformat(),
            "message": message,
            "sync_log_id": str(log.id),
        }

    # -------------------------------------------------------------- fetch
    def _fetch_prices(
        self,
        commodities: list[Commodity],
        markets: list[Market],
        from_date: date,
        to_date: date,
        history_days: int | None,
    ) -> list[tuple[PriceRecord, Market]]:
        """Fetch a record set and attach each row to a concrete market.

        Live providers key rows by market code; the demo provider has no upstream
        so it is asked to synthesise history per market instead.
        """
        codes = [c.code for c in commodities]
        market_codes = [m.code for m in markets]
        records = self.provider.fetch_prices(
            commodity_codes=codes,
            market_codes=market_codes,
            from_date=from_date,
            to_date=to_date,
        )
        if records:
            by_code = {m.code.upper(): m for m in markets}
            paired: list[tuple[PriceRecord, Market]] = []
            for record in records:
                market = by_code.get(record.market_code.upper())
                if market is not None:
                    paired.append((record, market))
            return paired

        if not self.provider.is_demo:
            return []

        window_days = history_days or DEFAULT_HISTORY_DAYS
        start = to_date - timedelta(days=max(0, window_days) - 1)
        paired = []
        for market in markets:
            bias = {code: self._bias_for(market, code) for code in codes}
            generated = self.provider.generate_history(
                commodity_codes=codes,
                market_bias=bias,
                from_date=start,
                to_date=to_date,
            )
            paired.extend((record, market) for record in generated)
        return paired

    def _bias_for(self, market: Market, commodity_code: str) -> float:
        """Per (market, commodity) multiplier, stable across runs."""
        from app.integrations.market_data.provider import DemoMarketDataProvider

        base = DemoMarketDataProvider.market_bias_for_market(market.name, market.district)
        # A small per-commodity tilt stops every crop quoting identically in a market.
        import hashlib

        tilt = int(hashlib.sha256(commodity_code.encode()).hexdigest()[:2], 16)
        return base * (0.95 + (tilt % 100) / 1000.0)

    def _sync_arrivals(
        self, commodities: list[Commodity], markets: list[Market], from_date: date, to_date: date
    ) -> int:
        records = self.provider.fetch_arrivals(
            commodity_codes=[c.code for c in commodities],
            market_codes=[m.code for m in markets],
            from_date=from_date,
            to_date=to_date,
        )
        if not records and self.provider.is_demo:
            # Derive arrivals from the price feed so the arrival-pressure signal
            # has data to work with in the demo deployment.
            for market in markets:
                records.extend(
                    ArrivalRecord(
                        market_code=market.code,
                        commodity_code=record.commodity_code,
                        arrival_date=record.price_date,
                        quantity=record.arrivals_quantity or 0.0,
                        unit=record.arrivals_unit,
                        source=record.source,
                    )
                    for record in self._demo_arrival_sources(
                        commodities, market, from_date, to_date
                    )
                )
        if not records:
            return 0

        commodity_by_code = {c.code.upper(): c for c in commodities}
        market_by_code = {m.code.upper(): m for m in markets}
        written = 0
        for record in records:
            commodity = commodity_by_code.get(record.commodity_code.upper())
            market = market_by_code.get(record.market_code.upper())
            if commodity is None or market is None:
                continue
            existing = (
                self.session.query(MarketArrival)
                .filter(
                    MarketArrival.market_id == market.id,
                    MarketArrival.commodity_id == commodity.id,
                    MarketArrival.arrival_date == record.arrival_date,
                )
                .one_or_none()
            )
            if existing is not None:
                existing.quantity = record.quantity
                existing.vehicle_count = record.vehicle_count
                continue
            self.session.add(
                MarketArrival(
                    market_id=market.id,
                    commodity_id=commodity.id,
                    arrival_date=record.arrival_date,
                    quantity=record.quantity,
                    unit=record.unit,
                    vehicle_count=record.vehicle_count,
                    source=record.source,
                )
            )
            written += 1
        self.session.flush()
        return written

    def _demo_arrival_sources(
        self, commodities: list[Commodity], market: Market, from_date: date, to_date: date
    ) -> list[PriceRecord]:
        bias = {c.code: self._bias_for(market, c.code) for c in commodities}
        try:
            return self.provider.generate_history(
                commodity_codes=[c.code for c in commodities],
                market_bias=bias,
                from_date=from_date,
                to_date=to_date,
            )
        except NotImplementedError:
            return []

    # ------------------------------------------------------------- upsert
    def _resolve_commodities(self, commodity_ids: list[uuid.UUID] | None) -> list[Commodity]:
        if commodity_ids:
            return [
                c
                for c in (self.session.get(Commodity, cid) for cid in commodity_ids)
                if c is not None and c.is_active
            ]
        return self.commodities.active()

    def _resolve_markets(self, market_ids: list[uuid.UUID] | None) -> list[Market]:
        if market_ids:
            return [
                m
                for m in (self.session.get(Market, mid) for mid in market_ids)
                if m is not None and m.is_active
            ]
        return self.markets.active()

    def _upsert_price(
        self,
        record: PriceRecord,
        commodities: list[Commodity],
        markets: list[Market],
        market: Market | None = None,
    ) -> str:
        """Insert or refresh one price row. Returns inserted/updated/skipped.

        ``market`` is supplied by the caller from the ``_fetch_prices`` pairing.
        The demo provider leaves ``record.market_code`` empty because it
        synthesises a series *for* a market rather than reading a market code off
        a feed, so re-resolving the market from the record alone would drop every
        generated row on the floor.
        """
        commodity = next(
            (c for c in commodities if c.code.upper() == record.commodity_code.upper()), None
        )
        if market is None:
            market = next(
                (m for m in markets if m.code.upper() == record.market_code.upper()), None
            )
        if commodity is None or market is None:
            return "skipped"
        source = record.source if record.source in SYNCABLE_SOURCES else "PARTNER_API"
        existing = (
            self.session.query(MarketPrice)
            .filter(
                MarketPrice.market_id == market.id,
                MarketPrice.commodity_id == commodity.id,
                MarketPrice.price_date == record.price_date,
            )
            .one_or_none()
        )
        if existing is not None:
            # Do not let a demo row overwrite a published government price.
            if existing.source in ("AGMARKET_API", "STATE_APMC") and source == "DEMO":
                return "skipped"
            existing.min_price = record.min_price
            existing.max_price = record.max_price
            existing.modal_price = record.modal_price
            existing.arrivals_quantity = record.arrivals_quantity
            existing.arrivals_unit = record.arrivals_unit
            existing.source = source
            return "updated"
        self.session.add(
            MarketPrice(
                market_id=market.id,
                commodity_id=commodity.id,
                price_date=record.price_date,
                min_price=record.min_price,
                max_price=record.max_price,
                modal_price=record.modal_price,
                arrivals_quantity=record.arrivals_quantity,
                arrivals_unit=record.arrivals_unit,
                unit=record.unit,
                source=source,
                is_demo=source == "DEMO",
            )
        )
        self.session.flush()
        return "inserted"

    # ------------------------------------------------------------ reports
    def health(self) -> dict[str, Any]:
        try:
            provider_up = self.provider.healthcheck()
        except Exception:
            provider_up = False
        commodity_count = len(self.commodities.active())
        market_count = len(self.markets.active())
        return {
            "provider": self.provider.name,
            "provider_reachable": provider_up,
            "is_demo_data": self.provider.is_demo,
            "commodities_configured": commodity_count,
            "markets_configured": market_count,
            "ready": provider_up and commodity_count > 0 and market_count > 0,
        }
