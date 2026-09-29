"""Market data provider abstraction.

``MarketDataProvider`` is the seam where a real feed (AGMARKET eNAM, state APMC
dashboard, a partner API, ...) plugs in. The bundled ``DemoMarketDataProvider``
serves clearly labelled synthetic history so the platform is demo-ready without
any external dependency.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class PriceRecord:
    market_code: str
    commodity_code: str
    price_date: date
    min_price: float
    max_price: float
    modal_price: float
    arrivals_quantity: float | None = None
    arrivals_unit: str = "quintal"
    unit: str = "quintal"
    variety: str | None = None
    source: str = "DEMO"
    source_reference: str | None = None


@dataclass(slots=True)
class ArrivalRecord:
    market_code: str
    commodity_code: str
    arrival_date: date
    quantity: float
    unit: str = "quintal"
    vehicle_count: int | None = None
    source: str = "DEMO"


@dataclass(slots=True)
class ProviderSyncResult:
    provider: str
    records_processed: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    arrivals: list[ArrivalRecord] = field(default_factory=list)
    message: str = ""
    is_demo: bool = True


class MarketDataProvider(abc.ABC):
    """Interface every market data source must implement."""

    name: str = "abstract"

    @abc.abstractmethod
    def fetch_prices(
        self,
        *,
        commodity_codes: list[str] | None = None,
        market_codes: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[PriceRecord]: ...

    @abc.abstractmethod
    def fetch_arrivals(
        self,
        *,
        commodity_codes: list[str] | None = None,
        market_codes: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ArrivalRecord]: ...

    def healthcheck(self) -> bool:
        return True

    @property
    def is_demo(self) -> bool:
        return True

    def generate_history(
        self,
        *,
        commodity_codes: list[str],
        market_bias: dict[str, float] | None = None,
        from_date: date,
        to_date: date,
    ) -> list[PriceRecord]:
        """Build a deterministic price series per commodity.

        Demo-only: there is nothing upstream to fetch, so history is synthesised
        from a seeded random walk anchored to a base price. Determinism matters -
        the same (commodity, day) always yields the same number, so charts and
        screenshots are reproducible.
        """
        raise NotImplementedError(
            f"{type(self).__name__} cannot synthesise history; configure a real feed."
        )


class DemoMarketDataProvider(MarketDataProvider):
    """Deterministic synthetic feed used for the hackathon demo.

    Values are generated from a seeded random walk anchored to a base price per
    commodity so the same date always yields the same number, which keeps charts
    and screenshots reproducible. The provider is only used by the seeder - the
    live API reads the rows the seeder persisted.
    """

    name = "demo"

    def __init__(self, base_prices: dict[str, float] | None = None) -> None:
        self._base = {
            "TOMATO": 1850.0,
            "ONION": 1420.0,
            "SOYBEAN": 4620.0,
            "WHEAT": 2480.0,
            "RICE": 2380.0,
            "SUGARCANE": 315.0,
            "COTTON": 7100.0,
            "GROUNDNUT": 6780.0,
            "MAIZE": 2270.0,
            "BAJRA": 2450.0,
            "TUR": 9200.0,
            "MOONG": 8450.0,
            "CHANA": 5920.0,
            "POTATO": 1420.0,
            "GREEN_CHILLI": 5600.0,
            "GINGER": 11800.0,
            "APPLE": 12400.0,
            "MILK": 62.0,
        }
        if base_prices:
            self._base.update(base_prices)

    def _series(self, commodity_code: str, day: date, market_bias: float) -> PriceRecord:
        import math
        import random

        base = self._base.get(commodity_code.upper(), 2000.0)
        rng = random.Random(f"{commodity_code}:{day.isoformat()}")
        seasonal = 1 + 0.12 * math.sin(day.timetuple().tm_yday / 365 * 2 * math.pi)
        noise = rng.uniform(-0.09, 0.09)
        modal = base * seasonal * market_bias * (1 + noise)
        spread = modal * rng.uniform(0.12, 0.26)
        return PriceRecord(
            market_code="",
            commodity_code=commodity_code.upper(),
            price_date=day,
            min_price=round(max(1.0, modal - spread / 2), 2),
            max_price=round(modal + spread / 2, 2),
            modal_price=round(modal, 2),
            arrivals_quantity=round(rng.uniform(40, 900), 2),
        )

    def fetch_prices(
        self,
        *,
        commodity_codes: list[str] | None = None,
        market_codes: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[PriceRecord]:
        """The demo provider does not invent rows at request time; the seeder
        persists them so every consumer sees the same dataset."""
        return []

    def fetch_arrivals(
        self,
        *,
        commodity_codes: list[str] | None = None,
        market_codes: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ArrivalRecord]:
        return []

    def generate_history(
        self,
        *,
        commodity_codes: list[str],
        market_bias: dict[str, float] | None = None,
        from_date: date,
        to_date: date,
    ) -> list[PriceRecord]:
        bias = market_bias or {}
        records: list[PriceRecord] = []
        day = from_date
        while day <= to_date:
            for code in commodity_codes:
                market_bias = bias.get(code, 1.0)
                record = self._series(code, day, market_bias)
                records.append(record)
            day = date.fromordinal(day.toordinal() + 1)
        return records

    @staticmethod
    def market_bias_for_market(market_name: str, district: str) -> float:
        """Stable per-market multiplier so different mandis quote different rates."""
        import hashlib

        digest = hashlib.sha256(f"{market_name}:{district}".encode()).hexdigest()
        return 0.92 + (int(digest[:4], 16) % 1600) / 1000.0


class HttpMarketDataProvider(MarketDataProvider):
    """Adapter for a generic REST endpoint returning price rows.

    Expected payload (JSON): ``{"records": [{"market_code": ..., ...}]}``.
    Configure with ``MARKET_DATA_PROVIDER=http``, ``MARKET_DATA_BASE_URL`` and
    ``MARKET_DATA_API_KEY``.
    """

    name = "http"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url or settings.MARKET_DATA_BASE_URL
        self.api_key = api_key or settings.MARKET_DATA_API_KEY
        self.timeout = timeout
        if not self.base_url:
            raise ExternalServiceError(
                "MARKET_DATA_BASE_URL must be set for the http provider.",
                code="MARKET_PROVIDER_NOT_CONFIGURED",
            )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            response = httpx.get(
                f"{self.base_url.rstrip('/')}{path}",
                params={k: v for k, v in params.items() if v},
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                f"Market data provider request failed: {exc}", code="MARKET_PROVIDER_ERROR"
            ) from exc
        except ValueError as exc:
            raise ExternalServiceError(
                "Market data provider returned a malformed response.",
                code="MARKET_PROVIDER_BAD_PAYLOAD",
            ) from exc

    def fetch_prices(
        self,
        *,
        commodity_codes: list[str] | None = None,
        market_codes: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[PriceRecord]:
        payload = self._get(
            "/prices",
            {
                "commodity": ",".join(commodity_codes or []),
                "market": ",".join(market_codes or []),
                "from": from_date.isoformat() if from_date else None,
                "to": to_date.isoformat() if to_date else None,
            },
        )
        records: list[PriceRecord] = []
        for row in payload.get("records", []):
            try:
                records.append(
                    PriceRecord(
                        market_code=str(row["market_code"]),
                        commodity_code=str(row["commodity_code"]),
                        price_date=date.fromisoformat(str(row["date"])),
                        min_price=float(row.get("min_price", 0)),
                        max_price=float(row.get("max_price", 0)),
                        modal_price=float(row["modal_price"]),
                        arrivals_quantity=_opt_float(row.get("arrivals")),
                        arrivals_unit=str(row.get("arrivals_unit", "quintal")),
                        unit=str(row.get("unit", "quintal")),
                        variety=row.get("variety"),
                        source=str(row.get("source", "PARTNER_API")),
                        source_reference=str(row.get("reference") or "") or None,
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("market_data.skip_malformed_row", error=str(exc))
        return records

    def fetch_arrivals(
        self,
        *,
        commodity_codes: list[str] | None = None,
        market_codes: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[ArrivalRecord]:
        payload = self._get(
            "/arrivals",
            {
                "commodity": ",".join(commodity_codes or []),
                "market": ",".join(market_codes or []),
                "from": from_date.isoformat() if from_date else None,
                "to": to_date.isoformat() if to_date else None,
            },
        )
        records: list[ArrivalRecord] = []
        for row in payload.get("records", []):
            try:
                records.append(
                    ArrivalRecord(
                        market_code=str(row["market_code"]),
                        commodity_code=str(row["commodity_code"]),
                        arrival_date=date.fromisoformat(str(row["date"])),
                        quantity=float(row["quantity"]),
                        unit=str(row.get("unit", "quintal")),
                        vehicle_count=row.get("vehicle_count"),
                        source=str(row.get("source", "PARTNER_API")),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("market_data.skip_malformed_arrival", error=str(exc))
        return records

    def healthcheck(self) -> bool:
        try:
            self._get("/health", {})
            return True
        except ExternalServiceError:
            return False

    @property
    def is_demo(self) -> bool:
        return False


def _opt_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(Decimal(str(value)))
    except Exception:  # pragma: no cover - defensive
        return None


_provider_registry: dict[str, type[MarketDataProvider]] = {
    "demo": DemoMarketDataProvider,
    "http": HttpMarketDataProvider,
    "agn": HttpMarketDataProvider,
    "apmc": HttpMarketDataProvider,
}


def get_market_data_provider(name: str | None = None) -> MarketDataProvider:
    key = (name or settings.MARKET_DATA_PROVIDER or "demo").lower()
    provider_cls = _provider_registry.get(key)
    if provider_cls is None:
        raise ExternalServiceError(
            f"Unknown market data provider '{key}'. "
            f"Available: {', '.join(sorted(_provider_registry))}.",
            code="MARKET_PROVIDER_UNKNOWN",
        )
    return provider_cls()
